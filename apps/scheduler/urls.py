from django.urls import path
from . import views

urlpatterns = [
    path("scheduler/", views.scheduler_page, name="scheduler"),
    path("api/v1/calendar/month", views.month_json, name="calendar-month"),
    path("api/v1/calendar/slots", views.slots_json, name="slots"),
    path("api/v1/meetings", views.book, name="book"),
    path("meetings/<uuid:meeting_id>/", views.confirmation, name="confirmation"),
    path("meetings/<uuid:meeting_id>/cancel/", views.cancel_booking, name="cancel-booking"),
]
