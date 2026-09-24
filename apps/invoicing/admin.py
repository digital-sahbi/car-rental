"""Invoicing admin."""
from __future__ import annotations

from django.contrib import admin

from .models import Invoice, InvoiceSequence


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number", "booking", "issued_at", "subtotal",
        "discount_amount", "vat_amount", "total_amount", "printed_count",
    )
    list_filter = ("sequence_year", "issued_at")
    search_fields = ("number", "booking__client__name", "booking__car__plate_number")
    date_hierarchy = "issued_at"
    list_select_related = ("booking",)

    # An invoice is an issued legal document: no editing, no deleting.
    readonly_fields = (
        "booking", "number", "sequence_year", "issued_at", "issued_by",
        "client_snapshot", "car_snapshot", "dates_snapshot", "price_snapshot",
        "options_snapshot", "subtotal", "promotion_code", "discount_amount",
        "vat_rate", "vat_amount", "total_amount", "pdf_file", "printed_count",
        "created_at", "updated_at", "is_deleted", "deleted_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(InvoiceSequence)
class InvoiceSequenceAdmin(admin.ModelAdmin):
    list_display = ("year", "last_number")

    def has_add_permission(self, request) -> bool:
        return False
