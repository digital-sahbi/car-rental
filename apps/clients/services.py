"""Clients service layer."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest

from apps.core.models import AuditAction
from apps.core.services import apply_form_data, business_diff, log_action, snapshot

from .models import Client


def clients_queryset():
    """Base queryset for listings."""
    return Client.objects.select_related("created_by")


def search_clients(term: str):
    """Search by name, phone, WhatsApp, email, document or country."""
    term = (term or "").strip()
    if not term:
        return clients_queryset()
    return clients_queryset().filter(
        Q(name__icontains=term)
        | Q(telephone__icontains=term)
        | Q(whatsapp__icontains=term)
        | Q(email__icontains=term)
        | Q(id_document__icontains=term)
        | Q(country__icontains=term)
    )


@transaction.atomic
def create_client(
    *,
    data: dict[str, Any],
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Client:
    """Create a client and audit it."""
    client = Client()
    apply_form_data(client, data)
    client.created_by = actor
    client.updated_by = actor
    client.full_clean()
    client.save()
    log_action(
        action=AuditAction.CREATE,
        instance=client,
        user=actor,
        request=request,
        changes={"created": {"name": client.name, "country": client.country}},
    )
    return client


@transaction.atomic
def update_client(
    *,
    client: Client,
    data: dict[str, Any],
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Client:
    """Update a client, logging only changed fields."""
    before = snapshot(client)
    apply_form_data(client, data)
    client.updated_by = actor
    client.full_clean()
    client.save()

    changes = business_diff(before, snapshot(client))
    if changes:
        log_action(
            action=AuditAction.UPDATE,
            instance=client,
            user=actor,
            request=request,
            changes=changes,
        )
    return client


@transaction.atomic
def delete_client(
    *,
    client: Client,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Client:
    """Soft-delete a client (blocks if they still have live bookings)."""
    client.delete()
    log_action(
        action=AuditAction.DELETE,
        instance=client,
        user=actor,
        request=request,
        changes={"is_deleted": {"old": False, "new": True}},
    )
    return client
