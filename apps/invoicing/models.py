"""Invoicing models.

An :class:`Invoice` is a **frozen** document: at issue time we copy the client,
car, dates, prices and extras into JSON snapshots. Editing the underlying Car
or Client afterwards must never change an already-issued invoice.

Because promotions are applied at invoice time only, the discount lives here —
``Booking.total_price`` stays the pure rental total.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import SoftDeleteModel, TimeStampedModel


class InvoiceSequence(models.Model):
    """Per-year counter backing the race-safe ``INV-YYYY-####`` numbering."""

    year = models.PositiveIntegerField(_("année"), unique=True)
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("compteur de factures")
        verbose_name_plural = _("compteurs de factures")

    def __str__(self) -> str:
        return f"{self.year}: {self.last_number}"


class Invoice(TimeStampedModel, SoftDeleteModel):
    """A printable, immutable invoice for one booking."""

    booking = models.OneToOneField(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="invoice",
        verbose_name=_("réservation"),
    )
    number = models.CharField(_("numéro"), max_length=32, unique=True, db_index=True)
    sequence_year = models.PositiveIntegerField(_("année de séquence"), default=0, db_index=True)
    issued_at = models.DateTimeField(_("émise le"), default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="issued_invoices",
        verbose_name=_("émise par"),
    )

    # -- immutable snapshots ------------------------------------------------
    client_snapshot = models.JSONField(_("client (instantané)"), default=dict, blank=True)
    car_snapshot = models.JSONField(_("véhicule (instantané)"), default=dict, blank=True)
    dates_snapshot = models.JSONField(_("dates (instantané)"), default=dict, blank=True)
    price_snapshot = models.JSONField(_("prix (instantané)"), default=dict, blank=True)
    options_snapshot = models.JSONField(_("options (instantané)"), default=list, blank=True)

    # -- amounts ------------------------------------------------------------
    subtotal = models.DecimalField(
        _("sous-total"), max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    promotion_code = models.CharField(_("code promotion"), max_length=32, blank=True)
    discount_amount = models.DecimalField(
        _("remise"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    vat_rate = models.DecimalField(
        _("TVA (%)"), max_digits=5, decimal_places=2, default=Decimal("20.00")
    )
    vat_amount = models.DecimalField(
        _("montant TVA"), max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total_amount = models.DecimalField(
        _("net à payer"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    pdf_file = models.FileField(_("fichier PDF"), upload_to="invoices/", null=True, blank=True)
    printed_count = models.PositiveIntegerField(_("nombre d'impressions"), default=0)

    class Meta:
        verbose_name = _("facture")
        verbose_name_plural = _("factures")
        ordering = ("-issued_at",)
        base_manager_name = "all_objects"
        indexes = [models.Index(fields=["sequence_year", "-issued_at"])]

    def __str__(self) -> str:
        return self.number

    @property
    def net_amount(self) -> Decimal:
        """Subtotal minus discount (before VAT)."""
        return (self.subtotal - self.discount_amount).quantize(Decimal("0.01"))

    @property
    def client_name(self) -> str:
        return self.client_snapshot.get("name", "") or "—"

    @property
    def car_label(self) -> str:
        snapshot = self.car_snapshot
        return f"{snapshot.get('brand', '')} {snapshot.get('model', '')}".strip() or "—"

    @property
    def plate_number(self) -> str:
        return self.car_snapshot.get("plate_number", "") or "—"

    def clean(self) -> None:
        super().clean()
        if self.discount_amount > self.subtotal:
            raise ValidationError(
                {"discount_amount": _("La remise ne peut dépasser le sous-total.")}
            )

    def save(self, *args, **kwargs):
        """Freeze the snapshots on first save (immutability)."""
        if self.pk is not None:
            original = Invoice.all_objects.filter(pk=self.pk).first()
            if original is not None and original.snapshot_payload() != self.snapshot_payload():
                raise ValidationError(
                    _("Une facture émise est immuable : créez un avoir au lieu de la modifier.")
                )
        return super().save(*args, **kwargs)

    def snapshot_payload(self) -> dict:
        """The parts of an invoice that must never change after issue."""
        return {
            "number": self.number,
            "booking": self.booking_id,
            "client": self.client_snapshot,
            "car": self.car_snapshot,
            "dates": self.dates_snapshot,
            "price": self.price_snapshot,
            "options": self.options_snapshot,
            "subtotal": str(self.subtotal),
            "discount": str(self.discount_amount),
            "vat_rate": str(self.vat_rate),
            "total": str(self.total_amount),
        }
