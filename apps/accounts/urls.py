from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("accounts/<int:user_id>/activate/", views.activate_user, name="activate-user"),
    path("dashboard/export/", views.dashboard_export, name="dashboard-export"),
]
