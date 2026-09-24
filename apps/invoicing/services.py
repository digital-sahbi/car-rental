"""Invoicing service layer.

Responsibilities: race-safe numbering, snapshot capture, amount computation,
and the PDF render. Views only orchestrate.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.bookings.models import Booking
from apps.core.models import AuditAction, CompanySettings, Promotion
from apps.core.services import log_action

from .models import Invoice, InvoiceSequence

TWO_PLACES = Decimal("0.01")


def _money(value) -> Decimal:
    """Coerce to a 2-decimal Decimal, rounding half up."""
    return Decimal(str(value or "0")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@transaction.atomic
def next_invoice_number(*, year: Optional[int] = None) -> str:
    """Return the next ``INV-YYYY-####`` number.

    Uses ``select_for_update`` on a per-year counter row, so two simultaneous
    issues cannot produce the same number. (On SQLite this is a no-op, but
    ``transaction_mode = IMMEDIATE`` already serialises writers.)
    """
    year = year or timezone.localdate().year

    sequence, _created = InvoiceSequence.objects.get_or_create(year=year)
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])

    return f"INV-{year}-{sequence.last_number:04d}"


def can_issue(booking: Booking) -> tuple[bool, str]:
    """Cheap pre-flight check used by views to hide/disable the button."""
    if hasattr(booking, "invoice") and booking.invoice is not None:
        return False, _("Cette réservation a déjà une facture.")
    if booking.total_price <= 0:
        return False, _("Le montant de la réservation est nul.")
    return True, ""


def build_snapshots(booking: Booking) -> dict:
    """Copy the booking's live data into JSON snapshots."""
    car = booking.car
    client = booking.client
    return {
        "client_snapshot": {
            "id": client.pk,
            "name": client.name,
            "telephone": client.telephone,
            "whatsapp": client.whatsapp,
            "email": client.email,
            "address": client.address,
            "country": client.country,
            "id_document": client.id_document,
        },
        "car_snapshot": {
            "id": car.pk,
            "brand": car.brand,
            "model": car.model,
            "name": car.name,
            "plate_number": car.plate_number,
            "category": car.category.get_name_display(),
            "fuel_type": car.get_fuel_type_display(),
            "transmission": car.get_transmission_display(),
            "year": car.year,
            "seats": car.seats,
        },
        "dates_snapshot": {
            "start_date": booking.start_date.isoformat(),
            "end_date": booking.end_date.isoformat(),
            "days": booking.days,
        },
        "price_snapshot": {
            "price_per_day": str(car.price_per_day),
            "days": booking.days,
            "base_price": str(booking.base_price),
            "options_total": str(booking.options_total),
            "total_price": str(booking.total_price),
        },
        "options_snapshot": [
            {
                "option_type": option.get_option_type_display(),
                "code": option.option_type,
                "price": str(option.price),
                "quantity": option.quantity,
                "subtotal": str(option.subtotal),
            }
            for option in booking.options.all()
        ],
    }


@transaction.atomic
def issue_invoice(
    *,
    booking: Booking,
    actor=None,
    promotion: Optional[Promotion] = None,
    request: Optional[HttpRequest] = None,
) -> Invoice:
    """Issue an invoice for ``booking``: snapshot, price, number, audit."""
    if hasattr(booking, "invoice") and booking.invoice is not None:
        raise ValidationError(_("Cette réservation a déjà une facture."))

    from apps.bookings.services import recalculate_total

    recalculate_total(booking)  # make sure we snapshot a fresh total

    settings_row = CompanySettings.load()
    vat_rate = _money(settings_row.default_vat)

    snapshots = build_snapshots(booking)
    subtotal = _money(booking.total_price)

    discount = Decimal("0.00")
    promotion_code = ""
    if promotion is not None:
        if not promotion.is_valid_now:
            raise ValidationError(
                _("La promotion « %(code)s » n'est pas valide aujourd'hui.")
                % {"code": promotion.code}
            )
        discount = promotion.discount_for(subtotal)
        promotion_code = promotion.code

    net = _money(subtotal - discount)
    vat_amount = _money(net * vat_rate / Decimal("100"))
    total = _money(net + vat_amount)

    invoice = Invoice(
        booking=booking,
        number=next_invoice_number(),
        sequence_year=timezone.localdate().year,
        issued_at=timezone.now(),
        issued_by=actor,
        subtotal=subtotal,
        promotion_code=promotion_code,
        discount_amount=discount,
        vat_rate=vat_rate,
        vat_amount=vat_amount,
        total_amount=total,
        **snapshots,
    )
    invoice.full_clean()
    invoice.save()

    log_action(
        action=AuditAction.CREATE,
        instance=invoice,
        user=actor,
        request=request,
        changes={
            "created": {
                "number": invoice.number,
                "booking": booking.pk,
                "subtotal": str(subtotal),
                "discount": str(discount),
                "total": str(total),
            }
        },
    )
    return invoice


def record_print(
    *,
    invoice: Invoice,
    actor=None,
    request: Optional[HttpRequest] = None,
) -> Invoice:
    """Increment the print counter and audit the PRINT action (requirement 7)."""
    invoice.printed_count += 1
    invoice.save(update_fields=["printed_count", "updated_at"])
    log_action(
        action=AuditAction.PRINT,
        instance=invoice,
        user=actor,
        request=request,
        changes={"printed_count": {"new": invoice.printed_count}},
    )
    return invoice


def invoices_queryset():
    """Base queryset for listings."""
    return Invoice.objects.select_related("booking", "booking__client", "booking__car", "issued_by")


def render_pdf(*, invoice: Invoice) -> bytes:
    """Render the invoice to PDF bytes with WeasyPrint."""
    from .pdf import render_invoice_pdf

    return render_invoice_pdf(invoice)
