from __future__ import annotations
from django.urls import path
from . import views

urlpatterns = [
    path("guide/", views.guide_page, name="guide"),
    path("guide/download/", views.guide_pdf, name="guide_pdf"),
]
