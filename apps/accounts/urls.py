"""Accounts URLs: auth + admin-only employee CRUD."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.CrmLoginView.as_view(), name="login"),
    path("logout/", views.CrmLogoutView.as_view(), name="logout"),
    # Admin-only employee management
    path("employees/", views.EmployeeListView.as_view(), name="employee_list"),
    path("employees/add/", views.EmployeeCreateView.as_view(), name="employee_add"),
    path("employees/<int:pk>/edit/", views.EmployeeUpdateView.as_view(), name="employee_edit"),
    path("employees/<int:pk>/toggle/", views.EmployeeToggleActiveView.as_view(), name="employee_toggle"),
]