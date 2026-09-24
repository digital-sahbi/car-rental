"""Vehicles admin."""
from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Car, CarCategory, CarImage, Maintenance


class CarImageInline(admin.TabularInline):
    model = CarImage
    extra = 1


class MaintenanceInline(admin.TabularInline):
    model = Maintenance
    extra = 0
    fields = ("date", "description", "cost", "mileage_at_service", "next_service_date")
    readonly_fields = ("created_at",)


@admin.register(CarCategory)
class CarCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = (
        "plate_number", "brand", "model", "category",
        "price_per_day", "status", "fuel_type", "transmission", "year", "is_deleted",
    )
    list_filter = ("status", "category", "fuel_type", "transmission", "is_deleted")
    search_fields = ("plate_number", "brand", "model", "name")
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")
    inlines = (CarImageInline, MaintenanceInline)
    list_select_related = ("category",)


@admin.register(Maintenance)
class MaintenanceAdmin(admin.ModelAdmin):
    list_display = ("car", "date", "cost", "mileage_at_service", "next_service_date")
    list_filter = ("date",)
    search_fields = ("car__plate_number", "description")
    date_hierarchy = "date"
    readonly_fields = ("created_at", "updated_at")
