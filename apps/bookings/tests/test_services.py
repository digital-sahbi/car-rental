"""Booking business rules: pricing, overbooking prevention, approval flow."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.bookings import services
from apps.bookings.models import Booking, BookingOption, BookingStatus, EditRequest
from apps.bookings.services import OverbookingError
from apps.core.tests.factories import (
    date_range,
    make_car,
    make_client,
    make_employee,
    make_manager,
)


class PricingTests(TestCase):
    """Requirement 5: the server owns the price."""

    def setUp(self):
        self.actor = make_employee()
        self.car = make_car(price_per_day="300.00")
        self.client = make_client()

    def test_days_are_inclusive_of_both_ends(self):
        start, end = date_range(start_offset=1, duration=2)  # 1 → 1+2 = 3 days
        booking = services.create_booking(
            data={
                "car": self.car,
                "client": self.client,
                "start_date": start,
                "end_date": end,
            },
            actor=self.actor,
        )
        self.assertEqual(booking.days, 3)
        self.assertEqual(booking.total_price, Decimal("900.00"))

    def test_options_are_added_to_the_total(self):
        booking = services.create_booking(
            data={
                "car": self.car,
                "client": self.client,
                **dict(zip(("start_date", "end_date"), date_range(start_offset=1, duration=1))),
            },
            options=[
                {"option_type": BookingOption.OptionType.GPS, "price": Decimal("50.00"), "quantity": 1},
                {"option_type": BookingOption.OptionType.CHILD_SEAT, "price": Decimal("40.00"), "quantity": 2},
            ],
            actor=self.actor,
        )
        # 2 days × 300 = 600, plus 50 + 80 = 730
        self.assertEqual(booking.total_price, Decimal("730.00"))

    def test_client_supplied_price_is_ignored(self):
        """``total_price`` comes from the form nowhere — it is recomputed."""
        start, end = date_range(start_offset=1, duration=1)
        booking = services.create_booking(
            data={
                "car": self.car,
                "client": self.client,
                "start_date": start,
                "end_date": end,
                "total_price": Decimal("1.00"),  # an attacker's value
            },
            actor=self.actor,
        )
        self.assertEqual(booking.total_price, Decimal("600.00"))


class OverbookingTests(TestCase):
    """Requirements 5 and 14: no two blocking bookings share a car's window."""

    def setUp(self):
        self.actor = make_employee()
        self.car = make_car(plate_number="99999-X-9")
        self.other_car = make_car(plate_number="88888-Y-8", price_per_day="400.00")
        self.client = make_client()
        self.start, self.end = date_range(start_offset=5, duration=4)

    def _book(self, *, car=None, start=None, end=None, status=BookingStatus.PENDING, client=None):
        return services.create_booking(
            data={
                "car": car or self.car,
                "client": client or self.client,
                "start_date": start or self.start,
                "end_date": end or self.end,
                "status": status,
            },
            actor=self.actor,
        )

    def test_exact_overlap_is_rejected(self):
        self._book()
        with self.assertRaises(OverbookingError):
            self._book()

    def test_partial_overlap_is_rejected(self):
        self._book()
        overlapping_start = self.start
        overlapping_end = self.end + timezone.timedelta(days=2)
        with self.assertRaises(OverbookingError):
            self._book(start=overlapping_start, end=overlapping_end)

    def test_contained_window_is_rejected(self):
        self._book()
        with self.assertRaises(OverbookingError):
            self._book(start=self.start + timezone.timedelta(days=1),
                       end=self.end - timezone.timedelta(days=1))

    def test_adjacent_booking_is_allowed(self):
        """Returning on day N and re-renting on day N+1 must be fine."""
        self._book()
        next_start = self.end + timezone.timedelta(days=1)
        next_end = next_start + timezone.timedelta(days=2)
        booking = self._book(start=next_start, end=next_end)
        self.assertIsNotNone(booking.pk)

    def test_different_car_same_window_is_allowed(self):
        self._book()
        booking = self._book(car=self.other_car)
        self.assertIsNotNone(booking.pk)

    def test_cancelled_booking_does_not_block(self):
        self._book(status=BookingStatus.CANCELLED)
        booking = self._book()  # same car and window
        self.assertIsNotNone(booking.pk)

    def test_completed_booking_does_not_block(self):
        self._book(status=BookingStatus.COMPLETED)
        booking = self._book()
        self.assertIsNotNone(booking.pk)

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._book(start=self.start, end=self.start - timezone.timedelta(days=1))

    def test_same_day_booking_is_rejected(self):
        """A zero-length window is not a rental."""
        with self.assertRaises(ValidationError):
            self._book(start=self.start, end=self.start)

    def test_editing_a_booking_ignores_its_own_window(self):
        booking = self._book()
        services.update_booking(
            booking=booking,
            data={"notes": "Updated without touching the dates"},
            actor=self.actor,
        )
        booking.refresh_from_db()
        self.assertEqual(booking.notes, "Updated without touching the dates")

    def test_reactivating_a_cancelled_booking_checks_overlap(self):
        cancelled = self._book(status=BookingStatus.CANCELLED)
        self._book()  # occupies the window
        with self.assertRaises(OverbookingError):
            services.change_status(
                booking=cancelled, status=BookingStatus.CONFIRMED, actor=self.actor
            )


class EditRequestWorkflowTests(TestCase):
    """Employees propose, managers approve."""

    def setUp(self):
        self.employee = make_employee()
        self.manager = make_manager()
        self.booking = services.create_booking(
            data={
                "car": make_car(plate_number="77777-Z-7"),
                "client": make_client(),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=10, duration=3))),
            },
            actor=self.employee,
        )

    def test_submitting_a_request_creates_a_pending_row(self):
        request_item = services.submit_edit_request(
            booking=self.booking,
            requested_by=self.employee,
            reason="Le client veut prolonger.",
            proposed_changes={"end_date": "2026-12-31"},
        )
        self.assertEqual(request_item.status, EditRequest.Status.PENDING)
        self.assertTrue(request_item.is_pending)

    def test_reason_is_mandatory(self):
        with self.assertRaises(ValidationError):
            services.submit_edit_request(
                booking=self.booking,
                requested_by=self.employee,
                reason="   ",
                proposed_changes={"end_date": "2026-12-31"},
            )

    def test_second_pending_request_is_refused(self):
        services.submit_edit_request(
            booking=self.booking,
            requested_by=self.employee,
            reason="Première demande",
            proposed_changes={"notes": "A"},
        )
        with self.assertRaises(ValidationError):
            services.submit_edit_request(
                booking=self.booking,
                requested_by=self.employee,
                reason="Deuxième demande",
                proposed_changes={"notes": "B"},
            )

    def test_approval_applies_the_proposed_changes(self):
        new_start, new_end = date_range(start_offset=30, duration=5)
        request_item = services.submit_edit_request(
            booking=self.booking,
            requested_by=self.employee,
            reason="Décaler la location",
            proposed_changes={
                "start_date": new_start.isoformat(),
                "end_date": new_end.isoformat(),
            },
        )

        services.review_edit_request(
            edit_request=request_item, approve=True, reviewer=self.manager
        )

        self.booking.refresh_from_db()
        request_item.refresh_from_db()
        self.assertEqual(self.booking.start_date, new_start)
        self.assertEqual(self.booking.end_date, new_end)
        self.assertEqual(request_item.status, EditRequest.Status.APPROVED)
        self.assertEqual(request_item.reviewed_by, self.manager)
        self.assertIsNotNone(request_item.reviewed_at)

    def test_rejection_leaves_the_booking_untouched(self):
        original_start = self.booking.start_date
        request_item = services.submit_edit_request(
            booking=self.booking,
            requested_by=self.employee,
            reason="Décaler la location",
            proposed_changes={"start_date": "2027-01-01"},
        )

        services.review_edit_request(
            edit_request=request_item, approve=False, reviewer=self.manager
        )

        self.booking.refresh_from_db()
        request_item.refresh_from_db()
        self.assertEqual(self.booking.start_date, original_start)
        self.assertEqual(request_item.status, EditRequest.Status.REJECTED)

    def test_a_reviewed_request_cannot_be_reviewed_again(self):
        request_item = services.submit_edit_request(
            booking=self.booking,
            requested_by=self.employee,
            reason="X",
            proposed_changes={"notes": "Y"},
        )
        services.review_edit_request(edit_request=request_item, approve=True, reviewer=self.manager)

        with self.assertRaises(ValidationError):
            services.review_edit_request(
                edit_request=request_item, approve=False, reviewer=self.manager
            )


class SoftDeleteTests(TestCase):
    """Deleted bookings disappear from the default manager but stay queryable."""

    def test_delete_is_soft(self):
        booking = services.create_booking(
            data={
                "car": make_car(plate_number="66666-W-6"),
                "client": make_client(),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=3, duration=2))),
            },
            actor=make_employee(),
        )
        services.delete_booking(booking=booking, actor=None)

        self.assertFalse(Booking.objects.filter(pk=booking.pk).exists())
        self.assertTrue(Booking.all_objects.filter(pk=booking.pk).exists())
        self.assertTrue(Booking.all_objects.get(pk=booking.pk).is_deleted)
