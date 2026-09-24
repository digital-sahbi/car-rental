"""Notification feed behind the header bell.

Two audiences, decided by role:

* **managers / administrators** → edit requests waiting for approval,
* **employees** → recent activity on the bookings they created.

"Unread" means *created after the user last opened the panel*
(``User.notifications_seen_at``), so opening the panel clears the badge until
something new arrives.

Nothing is stored in a dedicated table: the feed is derived from data that
already exists (``EditRequest`` and ``AuditLog``), which keeps it consistent
with the audit trail by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import AuditAction, AuditLog

#: How many items the dropdown panel shows.
PANEL_LIMIT = 8

#: Human labels for the audit actions surfaced in the feed.
ACTION_LABELS: dict[str, str] = {
    AuditAction.CREATE: _("créée"),
    AuditAction.UPDATE: _("modifiée"),
    AuditAction.DELETE: _("supprimée"),
    AuditAction.APPROVE: _("approuvée"),
    AuditAction.REJECT: _("rejetée"),
    AuditAction.PRINT: _("imprimée"),
}


@dataclass(frozen=True)
class Notification:
    """One row in the bell panel."""

    title: str
    detail: str
    url: str
    timestamp: datetime
    #: ``"edit_request"`` or ``"audit"`` — drives the icon.
    kind: str

    @property
    def is_recent(self) -> bool:
        """Created within the last hour."""
        return (timezone.now() - self.timestamp) < timezone.timedelta(hours=1)


# ---------------------------------------------------------------------------
# Feed builders
# ---------------------------------------------------------------------------


def _pending_edit_requests(*, limit: Optional[int] = None) -> list[Notification]:
    """Approval queue for managers and administrators."""
    from apps.bookings.models import EditRequest

    queryset = (
        EditRequest.objects.filter(status=EditRequest.Status.PENDING)
        .select_related("booking", "booking__client", "booking__car", "requested_by")
        .order_by("-created_at")
    )
    if limit is not None:
        queryset = queryset[:limit]

    return [
        Notification(
            title=_("Demande de modification à valider"),
            detail=_("#%(id)s %(client)s — %(requester)s")
            % {
                "id": request.booking_id,
                "client": request.booking.client.name,
                "requester": request.requested_by.get_full_name() or request.requested_by.email,
            },
            url=reverse("bookings:edit_request_list"),
            timestamp=request.created_at,
            kind="edit_request",
        )
        for request in queryset
    ]


def _visible_booking_events(user):
    """Audit rows about bookings ``user`` may see, plus their own requests."""
    from apps.bookings import services as booking_services
    from apps.bookings.models import EditRequest

    booking_ids = list(booking_services.bookings_visible_to(user).values_list("pk", flat=True))
    request_ids = list(EditRequest.objects.filter(requested_by=user).values_list("pk", flat=True))

    return AuditLog.objects.filter(
        Q(model_name="Booking", object_id__in=booking_ids)
        | Q(model_name="EditRequest", object_id__in=request_ids)
    ).select_related("user")


def _visible_booking_notifications(user, *, limit: Optional[int] = None) -> list[Notification]:
    """Activity feed built from the bookings the user may see."""
    from apps.bookings.models import EditRequest

    # Map each edit-request id to the booking it concerns, so a request entry
    # can link to that booking instead of the generic list.
    request_booking = dict(
        EditRequest.objects.filter(requested_by=user).values_list("pk", "booking_id")
    )

    queryset = _visible_booking_events(user).order_by("-timestamp")
    if limit is not None:
        queryset = queryset[:limit]

    notifications: list[Notification] = []
    for entry in queryset:
        if entry.model_name == "Booking":
            booking_id = entry.object_id
        else:
            booking_id = request_booking.get(entry.object_id)

        url = (
            reverse("bookings:booking_detail", args=[booking_id])
            if booking_id
            else reverse("bookings:booking_list")
        )

        actor = entry.user.get_full_name() if entry.user else _("Système")
        # ``object_repr`` already carries the reference, so it is used as-is
        # rather than prefixed with the id a second time.
        notifications.append(
            Notification(
                title=_("Réservation %(action)s")
                % {"action": ACTION_LABELS.get(entry.action, entry.action)},
                detail=f"{entry.object_repr} · {actor}"[:140],
                url=url,
                timestamp=entry.timestamp,
                kind="audit",
            )
        )
    return notifications


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def notifications_for(user, *, limit: int = PANEL_LIMIT) -> list[Notification]:
    """The panel's contents for ``user`` (newest first)."""
    if user is None or not user.is_authenticated:
        return []

    from apps.bookings.services import can_see_all_bookings

    if can_see_all_bookings(user):
        return _pending_edit_requests(limit=limit)
    return _visible_booking_notifications(user, limit=limit)


def unread_notification_count(user) -> int:
    """How many items arrived since the panel was last opened."""
    if user is None or not user.is_authenticated:
        return 0

    from apps.bookings.services import can_see_all_bookings

    seen = user.notifications_seen_at

    if can_see_all_bookings(user):
        from apps.bookings.models import EditRequest

        queryset = EditRequest.objects.filter(status=EditRequest.Status.PENDING)
        return queryset.filter(created_at__gt=seen).count() if seen else queryset.count()

    queryset = _visible_booking_events(user)
    return queryset.filter(timestamp__gt=seen).count() if seen else queryset.count()


def mark_notifications_seen(user) -> None:
    """Remember that ``user`` has just looked at the panel."""
    if user is None or not user.is_authenticated:
        return
    user.notifications_seen_at = timezone.now()
    user.save(update_fields=["notifications_seen_at"])


def activity_queryset_for(user):
    """Audit rows for the full activity page.

    Administrators browse the whole journal; everybody else only the entries
    about bookings they are allowed to see.
    """
    from apps.accounts.models import Role

    if getattr(user, "role", None) == Role.ADMIN:
        return AuditLog.objects.select_related("user")
    return _visible_booking_events(user).order_by("-timestamp")


def history_url_for(user) -> str:
    """Where "voir tout l'historique" should point for this user.

    Administrators keep the full, unrestricted audit journal; everybody else
    gets the scoped activity feed.
    """
    from apps.accounts.models import Role

    if getattr(user, "role", None) == Role.ADMIN:
        return reverse("core:audit_log")
    return reverse("core:activity")
