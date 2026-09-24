"""Vehicles service layer — all fleet writes go through here (requirement 9)."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.http import HttpRequest

from apps.core.models import AuditAction
from apps.core.services import apply_form_data, business_diff, log_action, snapshot

from .models import Car, CarStatus, Maintenance


def cars_queryset():
    """Base queryset for listings, with the relations the templates need."""
    return (
        Car.objects.select_related("category", "created_by")
        .prefetch_related("images")
    )


@transaction.atomic
def create_car(
    *,
    data: dict[str, Any],
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Car:
    """Create a car and audit it."""
    car = Car()
    apply_form_data(car, data)
    car.created_by = actor
    car.updated_by = actor
    car.full_clean(exclude=None)
    car.save()
    log_action(
        action=AuditAction.CREATE,
        instance=car,
        user=actor,
        request=request,
        changes={"created": {"plate_number": car.plate_number, "status": car.status}},
    )
    return car


@transaction.atomic
def update_car(
    *,
    car: Car,
    data: dict[str, Any],
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Car:
    """Update a car, logging only the fields that actually changed."""
    before = snapshot(car)
    # ``apply_form_data`` rather than a bare setattr, so that FileField's
    # None ("no change") vs False ("clear") contract is honoured.
    apply_form_data(car, data)
    car.updated_by = actor

    # Uploading (or clearing) the picture is an explicit choice of main photo,
    # so any gallery image previously promoted to main stands down. Without
    # this the new upload would be silently ignored by ``main_image``.
    if data.get("picture") is not None:
        demote_gallery_main(car=car)

    car.full_clean(exclude=None)
    car.save()

    changes = business_diff(before, snapshot(car))
    if changes:
        log_action(
            action=AuditAction.UPDATE,
            instance=car,
            user=actor,
            request=request,
            changes=changes,
        )
    return car


@transaction.atomic
def delete_car(*, car: Car, actor=None, request: Optional[HttpRequest] = None) -> Car:
    """Soft-delete a car (requirement 17 — never hard-delete)."""
    car.delete()
    log_action(
        action=AuditAction.DELETE,
        instance=car,
        user=actor,
        request=request,
        changes={"is_deleted": {"old": False, "new": True}},
    )
    return car


@transaction.atomic
def create_maintenance(
    *,
    car: Car,
    data: dict[str, Any],
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Maintenance:
    """Record a maintenance entry and optionally update mileage / status."""
    maintenance = Maintenance(car=car, created_by=actor, **data)
    maintenance.full_clean()
    maintenance.save()

    # Keep the odometer and status coherent with the intervention.
    updates: list[str] = []
    if maintenance.mileage_at_service and maintenance.mileage_at_service > car.mileage:
        car.mileage = maintenance.mileage_at_service
        updates.append("mileage")
    if car.status == CarStatus.MAINTENANCE:
        car.status = CarStatus.AVAILABLE
        updates.append("status")
    if updates:
        car.updated_by = actor
        car.save(update_fields=updates + ["updated_at"])

    log_action(
        action=AuditAction.CREATE,
        instance=maintenance,
        user=actor,
        request=request,
        changes={"created": {"car": car.plate_number, "date": str(maintenance.date)}},
    )
    return maintenance


def demote_gallery_main(*, car: Car) -> int:
    """Clear ``is_main`` on every gallery image of ``car``.

    ``Car.picture`` and ``CarImage.is_main`` are two competing claims to "the
    main photo"; this keeps the second one from overriding the first.
    Returns the number of rows changed.
    """
    return car.images.filter(is_main=True).update(is_main=False)


@transaction.atomic
def save_car_images(*, car: Car, formset, actor=None, request: Optional[HttpRequest] = None) -> list:
    """Persist a gallery formset, keeping exactly one "main" image.

    ``CarImage`` has a conditional unique constraint (one ``is_main`` per car),
    and an INSERT cannot succeed while another row still holds the flag. So we
    demote every other row *before* ``formset.save()``, keeping only the image
    the user flagged as main (the last one, if several were ticked).

    ``CarImageForm.validate_unique()`` is a deliberate no-op: a form is
    validated against the current database state, so promoting a new photo
    would always "clash" with the outgoing main before it could be demoted.
    This function restores the invariant that validation was forced to skip.
    """
    flagged = [
        form.instance
        for form in formset.forms
        if getattr(form, "cleaned_data", None)
        and form.cleaned_data.get("is_main")
        and not form.cleaned_data.get("DELETE")
    ]
    winner_pk = flagged[-1].pk if flagged and flagged[-1].pk else None

    others = car.images.all() if winner_pk is None else car.images.exclude(pk=winner_pk)
    others.update(is_main=False)

    saved = [image for image in formset.save() if image is not None]
    if saved:
        log_action(
            action=AuditAction.UPDATE,
            instance=car,
            user=actor,
            request=request,
            changes={"images": {"new": [image.image.name for image in saved]}},
        )
    return saved


def sync_status(*, car: Car, status: str, actor=None, request: Optional[HttpRequest] = None) -> Car:
    """Change a car's status, with an audit trail."""
    old = car.status
    if old == status:
        return car
    car.status = status
    car.updated_by = actor
    car.save(update_fields=["status", "updated_by", "updated_at"])
    log_action(
        action=AuditAction.UPDATE,
        instance=car,
        user=actor,
        request=request,
        changes={"status": {"old": old, "new": status}},
    )
    return car
