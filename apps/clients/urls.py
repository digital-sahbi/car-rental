"""Clients URLs."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("clients/", views.ClientListView.as_view(), name="client_list"),
    path("clients/add/", views.ClientCreateView.as_view(), name="client_add"),
    path("clients/<int:pk>/", views.ClientDetailView.as_view(), name="client_detail"),
    path("clients/<int:pk>/edit/", views.ClientUpdateView.as_view(), name="client_edit"),
    path("clients/<int:pk>/delete/", views.ClientDeleteView.as_view(), name="client_delete"),
]
