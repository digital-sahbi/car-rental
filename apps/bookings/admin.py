"""Bookings admin."""
from __future__ import annotations

from django.contrib import admin

from .models import Booking, BookingOption, EditRequest


class BookingOptionInline(admin.TabularInline):
    model = BookingOption
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id", "client", "car", "start_date", "end_date",
        "total_price", "status", "is_deleted",
    )
    list_filter = ("status", "is_deleted", "fuel_policy", "mileage_policy")
    search_fields = ("client__name", "car__plate_number", "car__brand", "car__model")
    date_hierarchy = "start_date"
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")
    inlines = (BookingOptionInline,)
    list_select_related = ("client", "car")
    autocomplete_fields = ("client",)


@admin.register(EditRequest)
class EditRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "requested_by", "status", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("status",)
    search_fields = ("booking__client__name", "reason")
    readonly_fields = ("created_at", "updated_at", "reviewed_at")
