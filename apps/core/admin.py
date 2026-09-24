"""Core admin registrations."""
from __future__ import annotations

from django.contrib import admin

from .models import AuditLog, CompanySettings, Promotion


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ("company_name", "phone", "email", "default_vat", "updated_at")

    def has_add_permission(self, request) -> bool:
        """Singleton: only one row, and it already exists."""
        return not CompanySettings.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "discount_value", "valid_from", "valid_to", "is_active")
    list_filter = ("discount_type", "is_active")
    search_fields = ("code", "description")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "model_name", "object_id", "object_repr", "user", "ip_address")
    list_filter = ("action", "model_name")
    search_fields = ("object_repr", "user__email")
    date_hierarchy = "timestamp"
    readonly_fields = (
        "user", "action", "model_name", "object_id",
        "object_repr", "changes", "ip_address", "timestamp",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Read-only journal."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
