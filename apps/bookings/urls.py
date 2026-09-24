"""Bookings URLs — preserves the routes from the spec."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("bookings/", views.BookingListView.as_view(), name="booking_list"),
    path("bookings/add/", views.BookingCreateView.as_view(), name="booking_add"),
    path("bookings/export/", views.BookingExportView.as_view(), name="booking_export"),
    path("bookings/<int:pk>/", views.BookingDetailView.as_view(), name="booking_detail"),
    path("bookings/<int:pk>/edit/", views.BookingEditDispatcherView.as_view(), name="booking_edit"),
    path("bookings/<int:pk>/update/", views.BookingUpdateView.as_view(), name="booking_update"),
    path("bookings/<int:pk>/status/", views.BookingStatusUpdateView.as_view(), name="booking_status"),
    path("bookings/<int:pk>/delete/", views.BookingDeleteView.as_view(), name="booking_delete"),
    path(
        "bookings/<int:pk>/edit-request/",
        views.EditRequestCreateView.as_view(),
        name="edit_request_create",
    ),
    # Manager queue
    path("edit-requests/", views.EditRequestListView.as_view(), name="edit_request_list"),
    path(
        "edit-requests/<int:pk>/review/",
        views.EditRequestReviewView.as_view(),
        name="edit_request_review",
    ),
]
