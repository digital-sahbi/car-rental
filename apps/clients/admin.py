"""Clients admin."""
from __future__ import annotations

from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "telephone", "whatsapp", "country", "id_document", "is_deleted")
    list_filter = ("country", "is_deleted")
    search_fields = ("name", "telephone", "whatsapp", "email", "id_document")
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")
