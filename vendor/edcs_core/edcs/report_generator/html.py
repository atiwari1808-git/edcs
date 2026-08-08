from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from edcs.models import ScanResult


def _env(template_dir: Path) -> Environment:
    return Environment(loader=FileSystemLoader(template_dir),
                       autoescape=select_autoescape(["html", "j2"]))  # XSS-safe


def summary_counts(r: ScanResult) -> dict:
    def count(findings, *cats):
        return sum(1 for f in findings if f.category in cats)
    return {
        "missing": count(r.doc_findings, "DOC_MISSING", "DOC_FOLDER_MISSING"),
        "blank": count(r.doc_findings, "DOC_BLANK", "DOC_TITLE_PAGE_ONLY", "DOC_IMAGE_ONLY"),
        "naming": count(r.doc_findings, "DOC_NAMING", "DOC_WRONG_JIRA", "DOC_NAME_FUZZY"),
        "corrupt": count(r.doc_findings, "DOC_CORRUPT", "DOC_PROTECTED", "DOC_TYPE_MISMATCH"),
        "secrets": count(r.code_findings, "SECRET"),
        "ips": count(r.code_findings, "IPV4", "IPV6"),
        "config_creds": count(r.code_findings, "CONFIG_CRED"),
    }


def write_html(r: ScanResult, template_dir: Path, dest: Path) -> Path:
    tpl = _env(template_dir).get_template("report.html.j2")
    dest.write_text(tpl.render(r=r, summary=summary_counts(r)), encoding="utf-8")
    return dest


def render_email_body(r: ScanResult, template_dir: Path) -> str:
    tpl = _env(template_dir).get_template("email_body.html.j2")
    return tpl.render(r=r, summary=summary_counts(r))
