"""Bookings models.

Replaces the legacy ``bicycle.Booking``. Two things are brand new and are the
reason this app exists as a separate unit:

* the customer is a :class:`clients.Client` (not an auth User), and
* pricing, overlap prevention and the approval workflow live in
  :mod:`apps.bookings.services`, never in the views.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AuditedModel, SoftDeleteModel, TimeStampedModel


class BookingStatus(models.TextChoices):
    PENDING = "pending", _("En attente")
    CONFIRMED = "confirmed", _("Confirmée")
    ONGOING = "ongoing", _("En cours")
    COMPLETED = "completed", _("Terminée")
    CANCELLED = "cancelled", _("Annulée")


#: Statuses that occupy a car and therefore block an overlapping booking.
BLOCKING_STATUSES = (
    BookingStatus.PENDING,
    BookingStatus.CONFIRMED,
    BookingStatus.ONGOING,
)


class FuelPolicy(models.TextChoices):
    FULL_TO_FULL = "full_to_full", _("Plein / Plein")
    FULL_TO_EMPTY = "full_to_empty", _("Plein / Vide")
    SAME_TO_SAME = "same_to_same", _("Même niveau")


class MileagePolicy(models.TextChoices):
    UNLIMITED = "unlimited", _("Kilométrage illimité")
    LIMITED = "limited", _("Kilométrage limité")


class Booking(TimeStampedModel, AuditedModel, SoftDeleteModel):
    """A vehicle rental for a client over a date range."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name=_("créée par"),
        help_text=_("Employé ayant enregistré la réservation."),
    )
    car = models.ForeignKey(
        "vehicles.Car",
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name=_("véhicule"),
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name=_("client"),
    )

    start_date = models.DateField(_("date de départ"), db_index=True)
    end_date = models.DateField(_("date de retour"), db_index=True)

    # Server-computed (requirement 5) — never read from the form.
    total_price = models.DecimalField(
        _("prix total"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    status = models.CharField(
        _("statut"),
        max_length=16,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
        db_index=True,
    )

    pickup_location = models.CharField(_("lieu de prise en charge"), max_length=150, blank=True)
    return_location = models.CharField(_("lieu de restitution"), max_length=150, blank=True)
    fuel_policy = models.CharField(
        _("politique carburant"), max_length=16, choices=FuelPolicy.choices, default=FuelPolicy.FULL_TO_FULL
    )
    mileage_policy = models.CharField(
        _("politique kilométrage"),
        max_length=16,
        choices=MileagePolicy.choices,
        default=MileagePolicy.UNLIMITED,
    )
    mileage_limit = models.PositiveIntegerField(
        _("limite de kilométrage (km)"), null=True, blank=True
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("réservation")
        verbose_name_plural = _("réservations")
        ordering = ("-start_date", "-id")
        base_manager_name = "all_objects"
        indexes = [
            models.Index(fields=["car", "start_date", "end_date"]),
            models.Index(fields=["status", "-start_date"]),
        ]
        constraints = [
            # DB-level guard (works on every backend). The stronger
            # no-overlap rule is enforced in services + on PostgreSQL by a
            # btree_gist exclusion constraint (see migration 0002).
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="booking_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(total_price__gte=0),
                name="booking_total_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.client} — {self.car.plate_number} ({self.start_date:%d/%m/%Y})"

    # -- pricing helpers ---------------------------------------------------

    @property
    def days(self) -> int:
        """Billed days, inclusive of both the pick-up and return date."""
        if not self.start_date or not self.end_date:
            return 0
        return max((self.end_date - self.start_date).days + 1, 0)

    @property
    def base_price(self) -> Decimal:
        """Car rental only (extras excluded)."""
        if not self.car_id:
            return Decimal("0.00")
        return (self.car.price_per_day * self.days).quantize(Decimal("0.01"))

    @property
    def options_total(self) -> Decimal:
        """Sum of every extra attached to this booking."""
        total = sum((option.subtotal for option in self.options.all()), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))

    # -- state helpers -----------------------------------------------------

    @property
    def blocks_availability(self) -> bool:
        """True while this booking holds the car."""
        return self.status in BLOCKING_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in (BookingStatus.CONFIRMED, BookingStatus.ONGOING)

    def clean(self) -> None:
        super().clean()
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError(
                {"end_date": _("La date de retour doit être postérieure à la date de départ.")}
            )
        if self.mileage_policy == MileagePolicy.LIMITED and not self.mileage_limit:
            raise ValidationError(
                {"mileage_limit": _("Indiquez la limite de kilométrage.")}
            )


class BookingOption(TimeStampedModel):
    """An extra billed on top of the rental (GPS, child seat, insurance…)."""

    class OptionType(models.TextChoices):
        GPS = "gps", _("GPS")
        CHILD_SEAT = "child_seat", _("Siège enfant")
        ADDITIONAL_DRIVER = "additional_driver", _("Conducteur additionnel")
        INSURANCE_FULL = "insurance_full", _("Assurance tous risques")
        INSURANCE_PARTIAL = "insurance_partial", _("Assurance partielle")
        DELIVERY = "delivery", _("Livraison / reprise")
        OTHER = "other", _("Autre")

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name=_("réservation"),
    )
    option_type = models.CharField(_("option"), max_length=24, choices=OptionType.choices)
    price = models.DecimalField(
        _("prix unitaire"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    quantity = models.PositiveSmallIntegerField(
        _("quantité"), default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        verbose_name = _("option de réservation")
        verbose_name_plural = _("options de réservation")
        ordering = ("option_type",)

    def __str__(self) -> str:
        return f"{self.get_option_type_display()} × {self.quantity}"

    @property
    def subtotal(self) -> Decimal:
        """``price × quantity``."""
        return (self.price * self.quantity).quantize(Decimal("0.01"))


class EditRequest(TimeStampedModel):
    """An employee's request to change a booking, pending manager approval.

    Employees cannot edit a booking directly; they file one of these and a
    manager/admin approves or rejects it (requirements: role-split edit flow).
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        APPROVED = "approved", _("Approuvée")
        REJECTED = "rejected", _("Rejetée")

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="edit_requests",
        verbose_name=_("réservation"),
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="edit_requests",
        verbose_name=_("demandeur"),
    )
    reason = models.TextField(_("motif"))
    proposed_changes = models.JSONField(
        _("modifications proposées"),
        default=dict,
        blank=True,
        help_text=_("Instantané des champs à modifier : {champ: nouvelle valeur}."),
    )
    status = models.CharField(
        _("statut"), max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_edit_requests",
        verbose_name=_("traité par"),
    )
    reviewed_at = models.DateTimeField(_("traité le"), null=True, blank=True)
    review_comment = models.TextField(_("commentaire de traitement"), blank=True)

    class Meta:
        verbose_name = _("demande de modification")
        verbose_name_plural = _("demandes de modification")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return _("Demande #%(id)s · %(booking)s") % {"id": self.pk, "booking": self.booking}

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING
