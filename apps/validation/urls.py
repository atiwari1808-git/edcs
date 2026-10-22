from django.urls import path
from . import views
from . import doc_only_go_live

urlpatterns = [
    path("verify/", views.verify_page, name="verify"),
    path("validate/", views.legacy_redirects),
    path("history/", views.legacy_redirects),

    path("api/v1/validations", views.start, name="validation-start"),
    path("api/v1/validations/<uuid:run_id>", views.status_json, name="validation-status"),
    path("api/v1/validations/<uuid:run_id>/cancel", views.cancel, name="validation-cancel"),

    path("validations/<uuid:run_id>/report/", views.report_page, name="report"),
    path("validations/<uuid:run_id>/report.pdf", views.report_pdf, name="report-pdf"),

    path("validations/<uuid:run_id>/go-live/", doc_only_go_live.mark_doc_go_live, name="validation-go-live"),
]

