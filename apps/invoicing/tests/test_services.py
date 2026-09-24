"""Invoice numbering, snapshots and immutability."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.bookings import services as booking_services
from apps.bookings.models import BookingOption
from apps.core.models import CompanySettings, DiscountType, Promotion
from apps.core.tests.factories import date_range, make_car, make_client, make_employee
from apps.invoicing import services
from apps.invoicing.models import Invoice


class InvoiceTestCase(TestCase):
    """Shared booking fixture.

    Note: the customer is stored as ``self.customer`` — ``self.client`` is
    Django's HTTP test client and must not be shadowed.
    """

    def setUp(self):
        self.actor = make_employee()
        self.car = make_car(plate_number="11111-A-1", price_per_day="300.00")
        self.customer = make_client()
        settings_row = CompanySettings.load()
        settings_row.default_vat = Decimal("20.00")
        settings_row.save()

    def make_booking(self, *, car=None, duration=2, start_offset=1, options=None):
        return booking_services.create_booking(
            data={
                "car": car or self.car,
                "client": self.customer,
                **dict(zip(("start_date", "end_date"), date_range(start_offset=start_offset, duration=duration))),
            },
            options=options,
            actor=self.actor,
        )


class NumberingTests(InvoiceTestCase):
    """Requirement 12: auto-numbered INV-YYYY-####."""

    def test_first_number_of_the_year(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)
        year = timezone.localdate().year
        self.assertEqual(invoice.number, f"INV-{year}-0001")

    def test_numbers_increment(self):
        second_car = make_car(plate_number="22222-B-2")
        first = services.issue_invoice(booking=self.make_booking(), actor=self.actor)
        second = services.issue_invoice(
            booking=self.make_booking(car=second_car, start_offset=20), actor=self.actor
        )
        self.assertEqual(first.number.split("-")[-1], "0001")
        self.assertEqual(second.number.split("-")[-1], "0002")

    def test_numbers_are_zero_padded_to_four_digits(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)
        self.assertRegex(invoice.number, r"^INV-\d{4}-\d{4}$")


class AmountTests(InvoiceTestCase):
    """Requirement 5: price = car × days + options − discount, plus VAT."""

    def test_subtotal_and_vat_are_computed(self):
        booking = self.make_booking(duration=2)  # 3 days × 300 = 900
        invoice = services.issue_invoice(booking=booking, actor=self.actor)

        self.assertEqual(invoice.subtotal, Decimal("900.00"))
        self.assertEqual(invoice.discount_amount, Decimal("0.00"))
        self.assertEqual(invoice.vat_amount, Decimal("180.00"))  # 20 %
        self.assertEqual(invoice.total_amount, Decimal("1080.00"))

    def test_options_are_included_in_the_subtotal(self):
        booking = self.make_booking(
            duration=1,  # 2 days × 300 = 600
            options=[{"option_type": BookingOption.OptionType.GPS, "price": Decimal("50.00"), "quantity": 2}],
        )
        invoice = services.issue_invoice(booking=booking, actor=self.actor)
        self.assertEqual(invoice.subtotal, Decimal("700.00"))

    def test_percentage_promotion_is_applied(self):
        promotion = Promotion.objects.create(
            code="TEN",
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )
        invoice = services.issue_invoice(
            booking=self.make_booking(duration=2), actor=self.actor, promotion=promotion
        )

        self.assertEqual(invoice.discount_amount, Decimal("90.00"))   # 10 % of 900
        self.assertEqual(invoice.promotion_code, "TEN")
        self.assertEqual(invoice.net_amount, Decimal("810.00"))
        self.assertEqual(invoice.vat_amount, Decimal("162.00"))
        self.assertEqual(invoice.total_amount, Decimal("972.00"))

    def test_fixed_promotion_is_capped_at_the_subtotal(self):
        promotion = Promotion.objects.create(
            code="BIG",
            discount_type=DiscountType.FIXED,
            discount_value=Decimal("99999.00"),
        )
        invoice = services.issue_invoice(
            booking=self.make_booking(duration=2), actor=self.actor, promotion=promotion
        )
        self.assertEqual(invoice.discount_amount, invoice.subtotal)
        self.assertEqual(invoice.total_amount, Decimal("0.00"))

    def test_expired_promotion_is_refused(self):
        today = timezone.localdate()
        promotion = Promotion.objects.create(
            code="OLD",
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            valid_to=today - timezone.timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            services.issue_invoice(
                booking=self.make_booking(), actor=self.actor, promotion=promotion
            )


class SnapshotTests(InvoiceTestCase):
    """Requirement 12: an issued invoice never changes."""

    def test_snapshot_captures_the_client_and_car(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)

        self.assertEqual(invoice.client_snapshot["name"], self.customer.name)
        self.assertEqual(invoice.car_snapshot["plate_number"], self.car.plate_number)
        self.assertEqual(invoice.dates_snapshot["days"], 3)
        self.assertEqual(invoice.price_snapshot["price_per_day"], "300.00")

    def test_changing_the_car_afterwards_does_not_alter_the_invoice(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)

        self.car.brand = "Peugeot"
        self.car.plate_number = "99999-Z-9"
        self.car.price_per_day = Decimal("900.00")
        self.car.save()

        invoice.refresh_from_db()
        self.assertEqual(invoice.car_snapshot["brand"], "Renault")
        self.assertEqual(invoice.car_snapshot["plate_number"], "11111-A-1")
        self.assertEqual(invoice.price_snapshot["price_per_day"], "300.00")
        self.assertEqual(invoice.total_amount, Decimal("1080.00"))

    def test_modifying_an_issued_invoice_is_refused(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)
        invoice.total_amount = Decimal("1.00")

        with self.assertRaises(ValidationError):
            invoice.save()

    def test_options_are_snapshotted(self):
        booking = self.make_booking(
            duration=1,
            options=[{"option_type": BookingOption.OptionType.GPS, "price": Decimal("50.00"), "quantity": 1}],
        )
        invoice = services.issue_invoice(booking=booking, actor=self.actor)

        self.assertEqual(len(invoice.options_snapshot), 1)
        self.assertEqual(invoice.options_snapshot[0]["subtotal"], "50.00")


class IssuingRulesTests(InvoiceTestCase):
    """One invoice per booking, and prints are counted."""

    def test_a_booking_cannot_be_invoiced_twice(self):
        booking = self.make_booking()
        services.issue_invoice(booking=booking, actor=self.actor)
        with self.assertRaises(ValidationError):
            services.issue_invoice(booking=booking, actor=self.actor)

    def test_record_print_increments_the_counter(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)
        services.record_print(invoice=invoice, actor=self.actor)
        services.record_print(invoice=invoice, actor=self.actor)

        invoice.refresh_from_db()
        self.assertEqual(invoice.printed_count, 2)

    def test_invoice_html_template_renders_the_expected_content(self):
        """The printable HTML invoice is the primary print path."""
        from django.template.loader import render_to_string

        booking = self.make_booking()
        invoice = services.issue_invoice(booking=booking, actor=self.actor)
        html = render_to_string("invoicing/invoice_pdf.html", {"invoice": invoice})

        self.assertIn(invoice.number, html)
        self.assertIn(invoice.client_snapshot["name"], html)
        self.assertIn(invoice.car_snapshot["plate_number"], html)

    def test_print_page_renders_and_counts_the_impression(self):
        booking = self.make_booking()
        invoice = services.issue_invoice(booking=booking, actor=self.actor)
        self.client.force_login(self.actor)

        from django.urls import reverse

        response = self.client.get(reverse("invoicing:invoice_print", args=[booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FACTURE")

        invoice.refresh_from_db()
        self.assertEqual(invoice.printed_count, 1)

    def _get_print_page(self, booking, language: str):
        """Fetch the printable invoice with ``language`` forced via cookie."""
        from django.conf import settings
        from django.urls import reverse

        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
        return self.client.get(reverse("invoicing:invoice_print", args=[booking.pk]))

    def test_print_page_is_rtl_when_the_language_is_arabic(self):
        """The invoice sheet must be right-to-left in Arabic.

        The invoice templates go through ``render_to_string`` without a request,
        so Django's context processors never run for them and ``is_rtl`` /
        ``current_language`` have to be supplied explicitly. Regression test for
        the sheet printing left-to-right next to right-to-left Arabic text.
        """
        booking = self.make_booking()
        services.issue_invoice(booking=booking, actor=self.actor)
        self.client.force_login(self.actor)

        response = self._get_print_page(booking, "ar")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('dir="rtl"', html)
        self.assertIn('lang="ar"', html)

    def test_print_page_is_ltr_when_the_language_is_french(self):
        booking = self.make_booking()
        services.issue_invoice(booking=booking, actor=self.actor)
        self.client.force_login(self.actor)

        response = self._get_print_page(booking, "fr")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('dir="ltr"', html)
        self.assertIn('lang="fr"', html)

    def test_print_page_body_is_translated_in_arabic(self):
        """The compiled ``ar`` catalogue must actually be reachable at runtime."""
        booking = self.make_booking()
        services.issue_invoice(booking=booking, actor=self.actor)
        self.client.force_login(self.actor)

        response = self._get_print_page(booking, "ar")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("FACTURE", html)
        self.assertIn("فاتورة", html)

    def test_print_page_body_is_translated_in_english(self):
        """Same guard for ``en``: an uncompiled catalogue would silently show French."""
        booking = self.make_booking()
        services.issue_invoice(booking=booking, actor=self.actor)
        self.client.force_login(self.actor)

        response = self._get_print_page(booking, "en")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("FACTURE", html)
        self.assertIn("INVOICE", html)

    def test_pdf_renders_a_real_pdf_when_the_backend_is_available(self):
        """WeasyPrint needs native GTK DLLs; skip honestly when they are absent."""
        booking = self.make_booking()
        invoice = services.issue_invoice(booking=booking, actor=self.actor)

        try:
            payload = services.render_pdf(invoice=invoice)
        except RuntimeError as exc:
            self.skipTest(f"PDF backend unavailable on this machine: {exc}")

        self.assertTrue(payload.startswith(b"%PDF"))

    def test_pdf_endpoint_degrades_gracefully_without_the_native_backend(self):
        """A missing GTK stack must surface as a message, not a 500."""
        from unittest import mock

        booking = self.make_booking()
        services.issue_invoice(booking=booking, actor=self.actor)
        self.client.force_login(self.actor)

        from django.urls import reverse

        with mock.patch(
            "apps.invoicing.views.services.render_pdf",
            side_effect=RuntimeError("backend missing"),
        ):
            response = self.client.get(reverse("invoicing:invoice_pdf", args=[booking.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], reverse("bookings:booking_detail", args=[booking.pk])
        )

    def test_invoice_is_excluded_from_the_default_manager_when_soft_deleted(self):
        invoice = services.issue_invoice(booking=self.make_booking(), actor=self.actor)
        invoice.delete()

        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())
        self.assertTrue(Invoice.all_objects.filter(pk=invoice.pk).exists())
