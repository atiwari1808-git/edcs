from django.urls import path
from . import views

urlpatterns = [
    path("login", views.graph_login, name="graph-login"),
    path("callback", views.graph_callback, name="graph-callback"),
]
