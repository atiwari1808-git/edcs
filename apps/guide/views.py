"""User Guide page + downloadable PDF for EDCS-Gate.

Self-contained: no models, no INSTALLED_APPS entry required (the app is only
needed on sys.path so its templates/urls resolve). Templates live in the
project-level templates/ directory (guide.html, guide_pdf.html).

The mandatory-documents section is read LIVE from the same checklist the
document scanner uses (config/mandatory_documents.yaml), so the Guide can never
drift out of sync with what the scanner actually enforces.
"""
from __future__ import annotations
import io
import logging
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string

log = logging.getLogger(__name__)

# Shown only when the live checklist genuinely can't be read, so the page is
# never empty. These mirror the typical EDCS handover set.
_FALLBACK_DOCS = [
    {"key": "TEST_REPORT",  "name": "Test Report",            "required": True,  "formats": [], "description": "Evidence that the automation was tested and the results."},
    {"key": "DESIGN_SPEC",  "name": "Design Specification",   "required": True,  "formats": [], "description": "How the automation is designed and works."},
    {"key": "RELEASE_NOTE", "name": "Release Note",           "required": True,  "formats": [], "description": "What is being delivered in this release."},
    {"key": "USER_GUIDE",   "name": "User Guide / Runbook",   "required": True,  "formats": [], "description": "How to run and operate the automation."},
    {"key": "UAT_SIGNOFF",  "name": "UAT Sign-off",           "required": True,  "formats": [], "description": "Customer / stakeholder acceptance sign-off."},
]


def _norm_formats(raw):
    """Coerce whatever the checklist stores for formats into a clean list."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for f in raw:
        f = str(f).strip().lstrip(".").lower()
        if f:
            out.append("." + f)
    return out


def _from_scanner_checklist():
    """Preferred source: the exact checklist object the scanner loads."""
    from edcs.config import get_settings                     # vendored edcs_core
    from edcs.document_scanner.scanner import DocumentScanner
    s = get_settings()
    checklist = DocumentScanner(s).checklist
    docs = []
    for d in getattr(checklist, "docs", []) or []:
        key = getattr(d, "key", "") or ""
        docs.append({
            "key": key,
            "name": (getattr(d, "display_name", "") or getattr(d, "name", "")
                     or key.replace("_", " ").title()),
            "required": bool(getattr(d, "required", True)),
            "formats": _norm_formats(getattr(d, "allowed_extensions", None)
                                     or getattr(d, "formats", None)
                                     or getattr(d, "extensions", None)),
            "description": getattr(d, "description", "") or "",
        })
    return docs


def _from_yaml():
    """Fallback: read config/mandatory_documents.yaml directly, flexibly."""
    import yaml
    candidates = []
    # explicit setting wins if the project defines one
    for attr in ("MANDATORY_DOCUMENTS_YAML", "CHECKLIST_PATH"):
        p = getattr(settings, attr, None)
        if p:
            candidates.append(str(p))
    env = os.environ.get("MANDATORY_DOCUMENTS_YAML")
    if env:
        candidates.append(env)
    base = getattr(settings, "BASE_DIR", ".")
    candidates += [
        os.path.join(str(base), "config", "mandatory_documents.yaml"),
        os.path.join(str(base), "mandatory_documents.yaml"),
    ]
    path = next((c for c in candidates if c and os.path.exists(c)), None)
    if not path:
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    # Accept: top-level list, or {"documents": [...]}, entries as strings
    # or dicts keyed by key/name/formats/required.
    if isinstance(data, dict):
        entries = data.get("documents") or data.get("mandatory_documents") or []
    else:
        entries = data or []

    docs = []
    for e in entries:
        if isinstance(e, str):
            docs.append({"key": e, "name": e.replace("_", " ").title(),
                         "required": True, "formats": [], "description": ""})
        elif isinstance(e, dict):
            key = str(e.get("key") or e.get("name") or "").strip()
            docs.append({
                "key": key,
                "name": str(e.get("display_name") or e.get("name") or key.replace("_", " ").title()),
                "required": bool(e.get("required", True)),
                "formats": _norm_formats(e.get("formats") or e.get("allowed_extensions")
                                         or e.get("extensions")),
                "description": str(e.get("description") or ""),
            })
    return docs


def _mandatory_documents():
    """Live mandatory-documents list, with graceful degradation.

    Returns (docs, source) where source is one of 'scanner', 'yaml', 'fallback'.
    """
    for loader, tag in ((_from_scanner_checklist, "scanner"), (_from_yaml, "yaml")):
        try:
            docs = loader()
            if docs:
                return docs, tag
        except Exception as exc:  # never let the Guide 500 over this
            log.info("Guide mandatory-docs %s loader skipped: %s", tag, exc)
    return _FALLBACK_DOCS, "fallback"


@login_required
def guide_page(request):
    docs, source = _mandatory_documents()
    return render(request, "guide.html", {
        "nav": "guide",
        "mandatory_docs": docs,
        "docs_source": source,
    })


@login_required
def guide_pdf(request):
    """Render the guide to a PDF and return it as a download."""
    from xhtml2pdf import pisa
    docs, source = _mandatory_documents()
    html = render_to_string("guide_pdf.html", {
        "mandatory_docs": docs,
        "docs_source": source,
    })
    buf = io.BytesIO()
    pisa.CreatePDF(html, dest=buf)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="EDCS-Gate-User-Guide.pdf"'
    return resp
