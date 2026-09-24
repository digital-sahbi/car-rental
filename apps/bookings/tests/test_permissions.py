"""Booking visibility: an employee only ever sees their own bookings.

Managers and administrators see everything. The rule lives in
``services.bookings_visible_to`` and must hold on *every* entry point — a list
filter alone would be bypassed by opening a URL directly.
"""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.bookings import services
from apps.core.tests.factories import (
    date_range,
    make_admin,
    make_car,
    make_client,
    make_employee,
    make_manager,
)


class BookingVisibilityTestCase(TestCase):
    """One booking created by an employee, one by a colleague."""

    def setUp(self):
        self.owner = make_employee(email="owner@smartrent.ma", first_name="Owner")
        self.other = make_employee(email="other@smartrent.ma", first_name="Other")
        self.manager = make_manager()
        self.admin = make_admin()

        self.mine = services.create_booking(
            data={
                "car": make_car(plate_number="VIS-001"),
                "client": make_client(name="My Client"),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=1, duration=2))),
            },
            actor=self.owner,
        )
        self.theirs = services.create_booking(
            data={
                "car": make_car(plate_number="VIS-002"),
                "client": make_client(name="Their Client"),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=10, duration=2))),
            },
            actor=self.other,
        )

    def listed_ids(self, **params) -> set[int]:
        response = self.client.get(reverse("bookings:booking_list"), params)
        self.assertEqual(response.status_code, 200)
        return {b.pk for b in response.context["bookings"]}


class BookingListVisibilityTests(BookingVisibilityTestCase):
    """The list itself."""

    def test_employee_only_sees_their_own_bookings(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.listed_ids(), {self.mine.pk})

    def test_employee_cannot_widen_the_scope_via_the_query_string(self):
        """``?mine=0`` must not unlock everybody else's bookings."""
        self.client.force_login(self.owner)
        self.assertEqual(self.listed_ids(mine="0"), {self.mine.pk})

    def test_employee_count_is_scoped_too(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_list"))
        self.assertEqual(response.context["total_count"], 1)

    def test_manager_sees_everything_by_default(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.listed_ids(), {self.mine.pk, self.theirs.pk})

    def test_manager_can_narrow_to_their_own_bookings(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.listed_ids(mine="1"), set())

    def test_admin_sees_everything(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.listed_ids(), {self.mine.pk, self.theirs.pk})

    def test_employee_export_is_scoped(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_export"), {"format": "csv"})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertIn("My Client", body)
        self.assertNotIn("Their Client", body)

    def test_manager_export_contains_everything(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("bookings:booking_export"), {"format": "csv"})
        body = response.content.decode("utf-8-sig")
        self.assertIn("My Client", body)
        self.assertIn("Their Client", body)


class BookingDetailVisibilityTests(BookingVisibilityTestCase):
    """Direct URL access — the part a list filter alone would miss."""

    def test_employee_can_open_their_own_booking(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_detail", args=[self.mine.pk]))
        self.assertEqual(response.status_code, 200)

    def test_employee_gets_403_on_a_colleagues_booking(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_detail", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 403)

    def test_employee_gets_403_on_a_colleagues_edit_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_edit", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 403)

    def test_employee_gets_403_on_a_colleagues_delete_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_delete", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 403)

    def test_employee_gets_403_changing_a_colleagues_status(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("bookings:booking_status", args=[self.theirs.pk]), {"status": "cancelled"}
        )
        self.assertEqual(response.status_code, 403)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, "pending")

    def test_employee_gets_403_printing_a_colleagues_invoice(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("invoicing:invoice_print", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 403)

    def test_employee_gets_403_downloading_a_colleagues_pdf(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("invoicing:invoice_pdf", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 403)

    def test_missing_booking_is_404_not_403(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("bookings:booking_detail", args=[999_999]))
        self.assertEqual(response.status_code, 404)

    def test_manager_can_open_a_colleagues_booking(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("bookings:booking_detail", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 200)


class DashboardVisibilityTests(BookingVisibilityTestCase):
    """The dashboard must not become a back door to other people's bookings."""

    def test_employee_recent_list_is_scoped(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:dashboard"))
        ids = {b.pk for b in response.context["recent_bookings"]}
        self.assertEqual(ids, {self.mine.pk})

    def test_manager_recent_list_shows_everything(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:dashboard"))
        ids = {b.pk for b in response.context["recent_bookings"]}
        self.assertEqual(ids, {self.mine.pk, self.theirs.pk})

    def test_scoped_flag_reflects_the_role(self):
        self.client.force_login(self.owner)
        self.assertTrue(self.client.get(reverse("core:dashboard")).context["scoped_to_me"])

        self.client.force_login(self.manager)
        self.assertFalse(self.client.get(reverse("core:dashboard")).context["scoped_to_me"])


class InvoiceListVisibilityTests(BookingVisibilityTestCase):
    """The invoice register follows the same rule."""

    def setUp(self):
        super().setUp()
        from apps.invoicing import services as invoice_services

        invoice_services.issue_invoice(booking=self.theirs, actor=self.other)
        invoice_services.issue_invoice(booking=self.mine, actor=self.owner)

    def numbers(self) -> set[str]:
        response = self.client.get(reverse("invoicing:invoice_list"))
        self.assertEqual(response.status_code, 200)
        return {invoice.number for invoice in response.context["invoices"]}

    def test_employee_only_sees_their_own_invoices(self):
        self.client.force_login(self.owner)
        numbers = self.numbers()
        self.assertEqual(len(numbers), 1)
        self.assertIn(self.mine.invoice.number, numbers)

    def test_manager_sees_all_invoices(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.numbers(), {self.mine.invoice.number, self.theirs.invoice.number}
        )
