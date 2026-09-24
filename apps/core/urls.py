"""Core URLs: dashboard, company settings, promotions, audit log."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Header bell
    path("notifications/seen/", views.MarkNotificationsSeenView.as_view(), name="notifications_seen"),
    path("activity/", views.ActivityHistoryView.as_view(), name="activity"),
    # Admin-only
    path("settings/", views.CompanySettingsUpdateView.as_view(), name="settings"),
    path("promotions/", views.PromotionListView.as_view(), name="promotion_list"),
    path("promotions/add/", views.PromotionCreateView.as_view(), name="promotion_add"),
    path("promotions/<int:pk>/edit/", views.PromotionUpdateView.as_view(), name="promotion_edit"),
    path("audit-log/", views.AuditLogListView.as_view(), name="audit_log"),
]
