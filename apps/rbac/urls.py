from django.urls import path
from . import views

urlpatterns = [
    path("manage/roles/", views.role_list, name="role-list"),
    path("manage/roles/new/", views.role_create, name="role-create"),
    path("manage/roles/<int:role_id>/edit/", views.role_edit, name="role-edit"),
    path("manage/roles/<int:role_id>/delete/", views.role_delete, name="role-delete"),
    path("manage/roles/<int:role_id>/clone/", views.role_clone, name="role-clone"),
    path("manage/users/", views.user_roles, name="user-roles"),
]
