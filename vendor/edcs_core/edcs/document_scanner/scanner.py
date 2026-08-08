"""Document scan pipeline: folder discovery -> doc discovery -> validators
-> score. Per-item isolation: one bad document never kills the job."""
from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from edcs.config import Settings
from edcs.content_validator import base as extractors  # noqa: F401 (registry)
from edcs.content_validator import blank_rules, corruption, docx, pdf, pptx, text, xlsx  # noqa: F401
from edcs.document_scanner import naming
from edcs.document_scanner.mandatory import Checklist, load_checklist, match_document
from edcs.document_scanner.scoring import DocState, compute_score
from edcs.eridoc_client.client import EridocClient
from edcs.eridoc_client import dql
from edcs.models import DocumentRecord, Finding, Severity

log = logging.getLogger(__name__)


def _rec(props: dict) -> DocumentRecord:
    ver = props.get("r_version_label")
    if isinstance(ver, list):
        ver = ",".join(str(v) for v in ver)
    return DocumentRecord(
        doc_id=str(props.get("r_object_id", "")),
        name=str(props.get("object_name", "")),
        version=str(ver or ""),
        owner=str(props.get("owner_name", "")),
        created=str(props.get("r_creation_date", "")),
        modified=str(props.get("r_modify_date", "")),
        file_type=str(props.get("a_content_type", "")),
        size_bytes=int(props.get("r_content_size", 0) or 0),
    )


class DocumentScanner:
    def __init__(self, s: Settings, client: EridocClient | None = None):
        self.s = s
        self.client = client or EridocClient(s)
        self.checklist: Checklist = load_checklist(s.mandatory_docs_file)

    # ------------------------------------------------------------------
    def scan(self, jira_id: str) -> tuple[list[Finding], list[DocumentRecord], int, list[str]]:
        findings: list[Finding] = []
        jira_id = dql.validate_jira_id(jira_id)

        # 1. Folder discovery ------------------------------------------------
        folders = self.client.dql(dql.folder_query(jira_id, self.s.eridoc_root_path))
        if not folders:
            findings.append(Finding(
                severity=Severity.CRITICAL, category="DOC_FOLDER_MISSING", file=jira_id,
                rule_id="EDCS-DOC-001", reason=f"No ERIDOC folder named {jira_id} exists",
                recommendation="Create the project folder in ERIDOC and upload all "
                               "mandatory documents."))
            score = compute_score([], self.checklist, folder_missing=True)
            return findings, [], score.score, score.caps_applied
        if len(folders) > 1:
            ids = ", ".join(str(f.get("r_object_id")) for f in folders)
            findings.append(Finding(
                severity=Severity.HIGH, category="DOC_FOLDER_DUPLICATE", file=jira_id,
                rule_id="EDCS-DOC-002",
                reason=f"{len(folders)} duplicate folders named {jira_id} ({ids}). "
                       "Scanning the union of their contents.",
                recommendation="Consolidate into a single project folder."))

        # 2. Document discovery (union across duplicates) ---------------------
        records: dict[str, DocumentRecord] = {}
        for folder in sorted(folders, key=lambda f: str(f.get("r_creation_date", ""))):
            for props in self.client.dql(dql.documents_query(str(folder["r_object_id"]))):
                r = _rec(props)
                records[r.doc_id] = r
        docs = list(records.values())
        if not docs:
            findings.append(Finding(
                severity=Severity.HIGH, category="DOC_FOLDER_EMPTY", file=jira_id,
                rule_id="EDCS-DOC-003", reason="Folder exists but contains no documents",
                recommendation="Upload all mandatory documents."))

        # 3. Classify against mandatory checklist ----------------------------
        states = {d.key: DocState(d.key, d.weight) for d in self.checklist.docs}
        doc_to_key: dict[str, str] = {}
        for r in docs:
            key, fuzzy = match_document(r.name, jira_id, self.checklist)
            if key:
                doc_to_key[r.doc_id] = key
                states[key].present = True
                if fuzzy:
                    findings.append(Finding(
                        severity=Severity.LOW, category="DOC_NAME_FUZZY", file=r.name,
                        rule_id="EDCS-DOC-013",
                        reason=f"Matched mandatory document '{key}' only via fuzzy matching",
                        recommendation="Align filename with the naming standard."))

        for key, st in states.items():
            if not st.present:
                sev = Severity.HIGH if st.weight >= 10 else Severity.MEDIUM
                findings.append(Finding(
                    severity=sev, category="DOC_MISSING", file=key, rule_id="EDCS-DOC-004",
                    reason=f"Mandatory document '{key}' not found in folder {jira_id}",
                    recommendation=f"Upload {jira_id}_{key}.<ext> to the ERIDOC folder."))

        # 4-8. Per-document validation ----------------------------------------
        with tempfile.TemporaryDirectory(prefix="edcs_docs_", dir=self.s.tmp_dir) as tmp:
            with ThreadPoolExecutor(max_workers=5) as pool:  # polite to ERIDOC
                futs = {pool.submit(self._validate_one, r, jira_id, Path(tmp),
                                    doc_to_key.get(r.doc_id), states): r for r in docs}
                for fut in as_completed(futs):
                    try:
                        findings.extend(fut.result())
                    except Exception as e:  # isolation: log + finding, continue
                        r = futs[fut]
                        log.exception("Validator crashed on %s", r.name)
                        findings.append(Finding(
                            severity=Severity.HIGH, category="DOC_CORRUPT", file=r.name,
                            rule_id="EDCS-DOC-005",
                            reason=f"Validation failed: {type(e).__name__}",
                            recommendation="Re-upload the document; verify it opens locally."))

        score = compute_score(list(states.values()), self.checklist)
        return findings, docs, score.score, score.caps_applied

    # ------------------------------------------------------------------
    def _validate_one(self, r: DocumentRecord, jira_id: str, tmp: Path,
                      mkey: str | None, states: dict) -> list[Finding]:
        out: list[Finding] = []
        out.extend(naming.check_name(r.name, jira_id))
        if mkey and any(f.category in ("DOC_NAMING", "DOC_WRONG_JIRA") for f in out):
            states[mkey].named_ok = False

        # metadata validation
        if not r.owner:
            out.append(Finding(Severity.LOW, "DOC_NO_OWNER", r.name,
                               "Document has no owner set", "Set the document owner in ERIDOC.",
                               "EDCS-DOC-006"))
        if not r.version:
            out.append(Finding(Severity.LOW, "DOC_NO_VERSION", r.name,
                               "Document has no version label", "Version the document in ERIDOC.",
                               "EDCS-DOC-007"))

        if r.size_bytes == 0:
            out.append(Finding(Severity.CRITICAL, "DOC_BLANK", r.name,
                               "Document content is 0 bytes",
                               "Upload the real document content.", "EDCS-DOC-008"))
            if mkey:
                states[mkey].blank = True
            return out

        ext = Path(r.name).suffix.lower()
        local = tmp / f"{r.doc_id}{ext}"
        if self.client.download(r.doc_id, local) is None:
            out.append(Finding(Severity.INFO, "DOC_OVERSIZE", r.name,
                               f"Document exceeds {self.s.eridoc_max_doc_mb} MB; "
                               "metadata-only validation performed",
                               "Consider splitting or compressing the document.",
                               "EDCS-DOC-009"))
            return out

        # corruption / protection / type checks
        reason = corruption.magic_mismatch(local)
        if reason:
            out.append(Finding(Severity.MEDIUM, "DOC_TYPE_MISMATCH", r.name, reason,
                               "Save the file in the format its extension claims.",
                               "EDCS-DOC-014"))
        reason = corruption.zip_integrity(local)
        if reason:
            out.append(Finding(Severity.HIGH, "DOC_CORRUPT", r.name, reason,
                               "Re-create and re-upload the document.", "EDCS-DOC-005"))
            if mkey:
                states[mkey].corrupt = True
            return out

        extractor = extractors.get_extractor(local)
        if extractor is None:
            out.append(Finding(Severity.INFO, "DOC_UNSUPPORTED", r.name,
                               f"No content validator for {ext} - content not verified",
                               "Prefer PDF/DOCX/XLSX/PPTX formats.", "EDCS-DOC-015"))
            return out

        res = extractor(local)
        if res.protected:
            out.append(Finding(Severity.HIGH, "DOC_PROTECTED", r.name,
                               "Document is password protected - compliance cannot be verified",
                               "Upload an unprotected copy to the controlled ERIDOC folder.",
                               "EDCS-DOC-016"))
            if mkey:
                states[mkey].protected = True
            return out
        if res.error:
            out.append(Finding(Severity.HIGH, "DOC_CORRUPT", r.name,
                               f"Document unreadable: {res.error[:120]}",
                               "Re-create and re-upload the document.", "EDCS-DOC-005"))
            if mkey:
                states[mkey].corrupt = True
            return out

        min_chars = blank_rules.DEFAULT_MIN_CHARS
        if mkey:
            min_chars = next((d.min_chars for d in self.checklist.docs if d.key == mkey),
                             min_chars)
        v = blank_rules.verdict(local, r.size_bytes, res, min_chars, self.checklist.boilerplate)
        if v == "BLANK":
            out.append(Finding(Severity.CRITICAL, "DOC_BLANK", r.name,
                               "Document contains no meaningful text",
                               "Provide the actual document content.", "EDCS-DOC-008"))
            if mkey:
                states[mkey].blank = True
        elif v == "TITLE_PAGE_ONLY":
            out.append(Finding(Severity.HIGH, "DOC_TITLE_PAGE_ONLY", r.name,
                               "Document appears to contain only a title page",
                               "Complete the document body.", "EDCS-DOC-017"))
            if mkey:
                states[mkey].blank = True
        elif v == "IMAGE_ONLY":
            out.append(Finding(Severity.HIGH, "DOC_IMAGE_ONLY", r.name,
                               "Document contains only images (likely a scan) - "
                               "text cannot be verified",
                               "Provide a text-searchable version.", "EDCS-DOC-018"))
        elif v == "SUSPECT_SMALL":
            out.append(Finding(Severity.MEDIUM, "DOC_SUSPECT_SMALL", r.name,
                               "Document is unusually small for its type - review manually",
                               "Verify the document is complete.", "EDCS-DOC-019"))

        # UAT sign-off content keyword check
        if mkey == "UAT_SIGNOFF" and res.text:
            low = res.text.lower()
            if not any(k in low for k in self.checklist.signoff_keywords):
                out.append(Finding(Severity.MEDIUM, "DOC_SIGNOFF_CONTENT", r.name,
                                   "UAT sign-off does not contain an approval keyword",
                                   "Attach the mail/document that shows explicit approval.",
                                   "EDCS-DOC-020"))
        return out
