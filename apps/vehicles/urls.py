"""Vehicles URLs."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "vehicles"

urlpatterns = [
    path("vehicles/", views.CarListView.as_view(), name="car_list"),
    path("vehicles/add/", views.CarCreateView.as_view(), name="car_add"),
    path("vehicles/<int:pk>/", views.CarDetailView.as_view(), name="car_detail"),
    path("vehicles/<int:pk>/edit/", views.CarUpdateView.as_view(), name="car_edit"),
    path("vehicles/<int:pk>/delete/", views.CarDeleteView.as_view(), name="car_delete"),
    path("vehicles/<int:pk>/status/", views.CarStatusUpdateView.as_view(), name="car_status"),
    path("vehicles/maintenance/", views.MaintenanceListView.as_view(), name="maintenance_list"),
    path("vehicles/maintenance/add/", views.MaintenanceCreateView.as_view(), name="maintenance_add"),
]
