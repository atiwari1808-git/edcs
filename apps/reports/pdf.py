"""Renders the same HTML used by the web report into a stored PDF."""
import io
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from xhtml2pdf import pisa


def render_run_pdf(run):
    from .context import build_report_context
    html = render_to_string("report_pdf.html", build_report_context(run))
    buf = io.BytesIO()
    pisa.CreatePDF(html, dest=buf)
    run.pdf_file.save(f"validation-{run.jira_id}-{run.id}.pdf",
                      ContentFile(buf.getvalue()), save=True)
    return run.pdf_file.name
