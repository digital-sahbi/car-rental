"""Bookings service layer — pricing, overbooking prevention, approval flow.

Nothing in :mod:`apps.bookings.views` computes a price or checks a date
overlap: all of it lives here (requirement 9), inside transactions.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.mixins import ADMIN, MANAGER
from apps.core.models import AuditAction
from apps.core.services import apply_form_data, business_diff, log_action, snapshot
from apps.vehicles.models import Car, CarStatus

from .models import (
    BLOCKING_STATUSES,
    Booking,
    BookingOption,
    BookingStatus,
    EditRequest,
)


class OverbookingError(ValidationError):
    """Raised when a booking would collide with an existing one."""


# ---------------------------------------------------------------------------
# Pricing (requirement 5 — never trust the client)
# ---------------------------------------------------------------------------


def billable_days(start: date, end: date) -> int:
    """Billed days, inclusive of pick-up and return (Marrakech agency rule)."""
    return max((end - start).days + 1, 0)


def calculate_price(*, car: Car, start: date, end: date) -> Decimal:
    """Rental price for a car over a date range (extras excluded)."""
    return (car.price_per_day * billable_days(start, end)).quantize(Decimal("0.01"))


def recalculate_total(booking: Booking) -> Decimal:
    """``car × days + Σ options``, stored back on the booking.

    Note: promotions are deliberately **not** applied here — the discount is
    recorded on the invoice at issue time (see :mod:`apps.invoicing.services`).
    """
    total = booking.base_price + booking.options_total
    booking.total_price = total.quantize(Decimal("0.01"))
    booking.save(update_fields=["total_price", "updated_at"])
    return booking.total_price


# ---------------------------------------------------------------------------
# Overbooking prevention (requirement 5 + 14)
# ---------------------------------------------------------------------------


def overlapping_bookings(
    *,
    car: Car,
    start: date,
    end: date,
    exclude_pk: Optional[int] = None,
):
    """Bookings that block ``car`` for the ``start``→``end`` window."""
    qs = Booking.objects.filter(
        car=car,
        status__in=BLOCKING_STATUSES,
        start_date__lte=end,
        end_date__gte=start,
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs


def assert_car_free(
    *,
    car: Car,
    start: date,
    end: date,
    exclude_pk: Optional[int] = None,
) -> None:
    """Raise :class:`OverbookingError` if the car is already taken.

    Locks the car row for the duration of the transaction so two concurrent
    requests cannot both pass the check. On SQLite ``select_for_update`` is a
    no-op, but ``transaction_mode = IMMEDIATE`` (see settings) takes the write
    lock at BEGIN, which serialises writers just as effectively.
    """
    if end <= start:
        raise OverbookingError(
            {"end_date": _("La date de retour doit être postérieure à la date de départ.")}
        )

    Car.objects.select_for_update().filter(pk=car.pk).first()

    clash = overlapping_bookings(car=car, start=start, end=end, exclude_pk=exclude_pk).first()
    if clash is not None:
        raise OverbookingError(
            {
                "start_date": _(
                    "Ce véhicule est déjà réservé du %(from)s au %(to)s (réservation #%(id)s)."
                )
                % {
                    "from": clash.start_date.strftime("%d/%m/%Y"),
                    "to": clash.end_date.strftime("%d/%m/%Y"),
                    "id": clash.pk,
                }
            }
        )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


#: Allowed orderings for the booking list, keyed by the ``sort`` GET value.
#: The default is "most recently created first" so a booking that was just
#: saved is immediately visible — sorting by rental start date (the model's
#: default) buries a new booking among the future ones.
BOOKING_SORTS: dict[str, tuple[str, ...]] = {
    "recent": ("-created_at", "-id"),
    "start_asc": ("start_date", "id"),
    "start_desc": ("-start_date", "-id"),
    "client": ("client__name", "start_date"),
    "car": ("car__plate_number", "start_date"),
}
DEFAULT_BOOKING_SORT = "recent"


def booking_sort_choices() -> list[tuple[str, str]]:
    """``(value, label)`` pairs for the list's sort selector."""
    return [
        ("recent", _("Plus récentes d'abord")),
        ("start_asc", _("Départ le plus proche")),
        ("start_desc", _("Départ le plus lointain")),
        ("client", _("Client (A → Z)")),
        ("car", _("Véhicule")),
    ]


def bookings_queryset():
    """Base queryset with everything the list/detail templates touch."""
    return (
        Booking.objects.select_related("car", "client", "user", "car__category")
        .prefetch_related("options")
    )


# ---------------------------------------------------------------------------
# Visibility (who may see whose booking)
# ---------------------------------------------------------------------------

#: Roles allowed to see every booking.
ALL_BOOKINGS_ROLES = (ADMIN, MANAGER)


def can_see_all_bookings(user) -> bool:
    """True for managers and administrators."""
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "role", None) in ALL_BOOKINGS_ROLES
    )


def bookings_visible_to(user, *, only_own: bool = False):
    """Queryset of the bookings ``user`` is allowed to see.

    Employees only ever see the bookings they created; managers and
    administrators see everything, unless they explicitly ask for ``only_own``.

    This is the *single* place booking visibility is decided. Every entry point
    — list, detail, edit, dashboard, invoice print/PDF — must go through it,
    otherwise the restriction is trivially bypassed by opening a URL directly.
    """
    qs = bookings_queryset()
    if only_own or not can_see_all_bookings(user):
        return qs.filter(user=user)
    return qs


def assert_booking_visible(*, booking: Booking, viewer) -> Booking:
    """Raise :class:`PermissionDenied` when ``viewer`` may not see ``booking``."""
    if not can_see_all_bookings(viewer) and booking.user_id != getattr(viewer, "pk", None):
        raise PermissionDenied(_("Vous n'avez pas accès à cette réservation."))
    return booking


def booking_for_viewer(*, pk: int, viewer) -> Booking:
    """Fetch one booking the viewer may see.

    Raises 403 for a booking that exists but belongs to somebody else, and 404
    when there is no such booking at all.
    """
    booking = bookings_visible_to(viewer).filter(pk=pk).first()
    if booking is not None:
        return booking
    if Booking.all_objects.filter(pk=pk, is_deleted=False).exists():
        raise PermissionDenied(_("Vous n'avez pas accès à cette réservation."))
    raise Http404(_("Réservation introuvable."))


def search_bookings(
    *,
    viewer,
    q: str = "",
    status: str = "",
    car_id: str = "",
    client_id: str = "",
    sort: str = "",
    only_own: bool = False,
):
    """Filtered, ordered, **scoped** booking list.

    ``viewer`` is a required keyword argument on purpose: visibility must never
    be forgotten by a caller.
    """
    qs = bookings_visible_to(viewer, only_own=only_own)
    if q:
        qs = qs.filter(
            Q(client__name__icontains=q)
            | Q(client__telephone__icontains=q)
            | Q(car__plate_number__icontains=q)
            | Q(car__brand__icontains=q)
            | Q(car__model__icontains=q)
            | Q(pickup_location__icontains=q)
        )
    if status in BookingStatus.values:
        qs = qs.filter(status=status)
    if car_id:
        qs = qs.filter(car_id=car_id)
    if client_id:
        qs = qs.filter(client_id=client_id)

    ordering = BOOKING_SORTS.get(sort or DEFAULT_BOOKING_SORT)
    return qs.order_by(*ordering) if ordering else qs


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@transaction.atomic
def create_booking(
    *,
    data: dict[str, Any],
    options: Optional[list[dict[str, Any]]] = None,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Booking:
    """Create a booking: validates the window, prices it, audits it."""
    car: Car = data["car"]
    start: date = data["start_date"]
    end: date = data["end_date"]

    assert_car_free(car=car, start=start, end=end)

    booking = Booking(
        user=actor,
        created_by=actor,
        updated_by=actor,
        **data,
    )
    booking.total_price = calculate_price(car=car, start=start, end=end)
    booking.full_clean(exclude=["user"])
    booking.save()

    for option in options or []:
        BookingOption.objects.create(booking=booking, **option)

    recalculate_total(booking)
    _sync_car_status(car=car, actor=actor, request=request)

    log_action(
        action=AuditAction.CREATE,
        instance=booking,
        user=actor,
        request=request,
        changes={
            "created": {
                "client": booking.client.name,
                "car": car.plate_number,
                "start_date": str(booking.start_date),
                "end_date": str(booking.end_date),
                "total_price": str(booking.total_price),
            }
        },
    )
    return booking


@transaction.atomic
def update_booking(
    *,
    booking: Booking,
    data: dict[str, Any],
    options: Optional[list[dict[str, Any]]] = None,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Booking:
    """Update a booking, re-validating dates, overlap and price."""
    before = snapshot(booking)
    old_car = booking.car

    car: Car = data.get("car", booking.car)
    start: date = data.get("start_date", booking.start_date)
    end: date = data.get("end_date", booking.end_date)

    assert_car_free(car=car, start=start, end=end, exclude_pk=booking.pk)

    apply_form_data(booking, data)
    booking.updated_by = actor
    booking.full_clean(exclude=["user"])
    booking.save()

    if options is not None:
        booking.options.all().delete()
        for option in options:
            BookingOption.objects.create(booking=booking, **option)

    recalculate_total(booking)

    _sync_car_status(car=old_car, actor=actor, request=request)
    if car.pk != old_car.pk:
        _sync_car_status(car=car, actor=actor, request=request)

    changes = business_diff(before, snapshot(booking))
    if changes:
        log_action(
            action=AuditAction.UPDATE,
            instance=booking,
            user=actor,
            request=request,
            changes=changes,
        )
    return booking


@transaction.atomic
def change_status(
    *,
    booking: Booking,
    status: str,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Booking:
    """Change a booking's status and keep the car's status in sync."""
    if status not in BookingStatus.values:
        raise ValidationError(_("Statut invalide."))

    old = booking.status
    if old == status:
        return booking

    # Re-check the car is free before re-activating a blocked window.
    if status in BLOCKING_STATUSES:
        assert_car_free(
            car=booking.car,
            start=booking.start_date,
            end=booking.end_date,
            exclude_pk=booking.pk,
        )

    booking.status = status
    booking.updated_by = actor
    booking.save(update_fields=["status", "updated_by", "updated_at"])
    _sync_car_status(car=booking.car, actor=actor, request=request)

    log_action(
        action=AuditAction.UPDATE,
        instance=booking,
        user=actor,
        request=request,
        changes={"status": {"old": old, "new": status}},
    )
    return booking


@transaction.atomic
def delete_booking(
    *,
    booking: Booking,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Booking:
    """Soft-delete a booking."""
    booking.delete()
    _sync_car_status(car=booking.car, actor=actor, request=request)
    log_action(
        action=AuditAction.DELETE,
        instance=booking,
        user=actor,
        request=request,
        changes={"is_deleted": {"old": False, "new": True}},
    )
    return booking


def _sync_car_status(*, car: Car, actor=None, request: Optional[HttpRequest] = None) -> None:
    """Reflect today's bookings on ``car.status`` (never overrides maintenance)."""
    if car.status in (CarStatus.MAINTENANCE, CarStatus.OUT_OF_SERVICE):
        return

    today = timezone.localdate()
    on_road = Booking.objects.filter(
        car=car,
        status__in=(BookingStatus.CONFIRMED, BookingStatus.ONGOING),
        start_date__lte=today,
        end_date__gte=today,
    ).exists()

    target = CarStatus.RENTED if on_road else CarStatus.AVAILABLE
    if car.status != target:
        car.status = target
        car.updated_by = actor
        car.save(update_fields=["status", "updated_by", "updated_at"])


# ---------------------------------------------------------------------------
# Edit-request workflow
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_edit_request(
    *,
    booking: Booking,
    requested_by,
    reason: str,
    proposed_changes: dict[str, Any],
    request: Optional[HttpRequest] = None,
) -> EditRequest:
    """File a change request (employees cannot edit a booking directly)."""
    if not reason.strip():
        raise ValidationError({"reason": _("Le motif est obligatoire.")})

    pending = booking.edit_requests.filter(status=EditRequest.Status.PENDING).exists()
    if pending:
        raise ValidationError(
            _("Une demande est déjà en attente pour cette réservation.")
        )

    edit_request = EditRequest.objects.create(
        booking=booking,
        requested_by=requested_by,
        reason=reason.strip(),
        proposed_changes={k: str(v) for k, v in proposed_changes.items()},
    )
    log_action(
        action=AuditAction.CREATE,
        instance=edit_request,
        user=requested_by,
        request=request,
        changes={"proposed_changes": edit_request.proposed_changes},
    )
    return edit_request


@transaction.atomic
def review_edit_request(
    *,
    edit_request: EditRequest,
    approve: bool,
    reviewer,
    comment: str = "",
    request: Optional[HttpRequest] = None,
) -> EditRequest:
    """Approve (and apply) or reject an edit request."""
    if not edit_request.is_pending:
        raise ValidationError(_("Cette demande a déjà été traitée."))

    edit_request.status = (
        EditRequest.Status.APPROVED if approve else EditRequest.Status.REJECTED
    )
    edit_request.reviewed_by = reviewer
    edit_request.reviewed_at = timezone.now()
    edit_request.review_comment = comment
    edit_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_comment", "updated_at"])

    if approve:
        _apply_proposed_changes(edit_request=edit_request, actor=reviewer, request=request)

    log_action(
        action=AuditAction.APPROVE if approve else AuditAction.REJECT,
        instance=edit_request,
        user=reviewer,
        request=request,
        changes={
            "status": {"old": EditRequest.Status.PENDING, "new": edit_request.status},
            "applied": edit_request.proposed_changes if approve else {},
        },
    )
    return edit_request


def _apply_proposed_changes(
    *,
    edit_request: EditRequest,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Booking:
    """Apply the approved payload to the booking, coercing values by field."""
    from django.db.models import DateField, ForeignKey

    booking = edit_request.booking
    data: dict[str, Any] = {}
    for field_name, raw_value in edit_request.proposed_changes.items():
        if field_name not in {"car", "client", "start_date", "end_date", "status",
                              "pickup_location", "return_location", "fuel_policy",
                              "mileage_policy", "mileage_limit", "notes"}:
            continue
        field = booking._meta.get_field(field_name)
        value: Any = raw_value
        if isinstance(field, ForeignKey):
            model = field.related_model
            value = model.objects.filter(pk=raw_value).first()
            if value is None:
                continue
        elif isinstance(field, DateField):
            try:
                value = date.fromisoformat(str(raw_value))
            except ValueError:
                continue
        data[field_name] = value

    if data:
        return update_booking(booking=booking, data=data, actor=actor, request=request)
    return booking
