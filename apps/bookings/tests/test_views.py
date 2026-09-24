"""Role-based access control and the employee-edit workflow over HTTP."""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.bookings import services
from apps.bookings.models import BookingStatus
from apps.core.tests.factories import (
    DEFAULT_PASSWORD,
    date_range,
    make_admin,
    make_car,
    make_client,
    make_employee,
    make_manager,
)


class LoginTests(TestCase):
    """Login is by email, not username."""

    def setUp(self):
        self.admin = make_admin()

    def test_email_login_works(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.admin.email, "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.admin.email, "password": "nope"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class RouteProtectionTests(TestCase):
    """Requirement 2: every route requires login."""

    def test_anonymous_user_is_redirected_to_login(self):
        for url in (
            reverse("core:dashboard"),
            reverse("bookings:booking_list"),
            reverse("vehicles:car_list"),
            reverse("clients:client_list"),
            reverse("invoicing:invoice_list"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])


class AdminOnlyRouteTests(TestCase):
    """Requirement 4: employee CRUD, settings, promotions, audit log."""

    def setUp(self):
        self.admin = make_admin()
        self.manager = make_manager()
        self.employee = make_employee()

    def test_employee_gets_403_on_employee_list(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("accounts:employee_list")).status_code, 403
        )

    def test_manager_gets_403_on_employee_list(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse("accounts:employee_list")).status_code, 403
        )

    def test_admin_can_open_employee_list(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("accounts:employee_list")).status_code, 200
        )

    def test_manager_gets_403_on_company_settings(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("core:settings")).status_code, 403)

    def test_manager_gets_403_on_audit_log(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("core:audit_log")).status_code, 403)

    def test_manager_can_open_edit_request_queue(self):
        """Managers are allowed on /edit-requests/."""
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse("bookings:edit_request_list")).status_code, 200
        )

    def test_employee_gets_403_on_edit_request_queue(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("bookings:edit_request_list")).status_code, 403
        )

    def test_employee_cannot_self_deactivate(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:employee_toggle", args=[self.admin.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


class EditRouteBranchingTests(TestCase):
    """``/bookings/<id>/edit`` behaves differently per role (the spec's rule)."""

    def setUp(self):
        self.admin = make_admin()
        self.manager = make_manager()
        self.employee = make_employee()
        self.booking = services.create_booking(
            data={
                "car": make_car(plate_number="55555-V-5"),
                "client": make_client(),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=4, duration=3))),
            },
            actor=self.employee,
        )

    def test_admin_is_redirected_to_the_direct_edit_form(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("bookings:booking_edit", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("bookings:booking_update", args=[self.booking.pk]),
        )

    def test_manager_is_redirected_to_the_direct_edit_form(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("bookings:booking_edit", args=[self.booking.pk]))
        self.assertEqual(
            response["Location"],
            reverse("bookings:booking_update", args=[self.booking.pk]),
        )

    def test_employee_gets_the_request_form(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("bookings:booking_edit", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "bookings/edit_request_form.html")

    def test_employee_cannot_reach_the_direct_edit_view(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("bookings:booking_update", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 403)


class BookingPageSmokeTests(TestCase):
    """The key pages render for an authenticated employee."""

    def setUp(self):
        self.employee = make_employee()
        self.client.force_login(self.employee)

    def test_dashboard_renders(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/dashboard.html")

    def test_booking_pages_render(self):
        for url in (
            reverse("bookings:booking_list"),
            reverse("bookings:booking_add"),
            reverse("vehicles:car_list"),
            reverse("clients:client_list"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_export_returns_csv_and_xlsx(self):
        csv_response = self.client.get(reverse("bookings:booking_export"), {"format": "csv"})
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response["Content-Type"])

        xlsx_response = self.client.get(reverse("bookings:booking_export"), {"format": "xlsx"})
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertIn("spreadsheetml", xlsx_response["Content-Type"])


class BookingListOrderingTests(TestCase):
    """A freshly created booking must be easy to find in the list.

    Regression: the list inherited ``Booking.Meta.ordering`` (by rental start
    date), so a booking created for today sat *below* every future booking —
    it looked like it had not been saved, even though it was there.
    """

    def setUp(self):
        self.employee = make_employee()
        self.client.force_login(self.employee)

        # Two bookings on different cars: one starting today, one next month.
        self.today_booking = services.create_booking(
            data={
                "car": make_car(plate_number="ORD-001"),
                "client": make_client(name="Zoe Zenith"),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=0, duration=2))),
            },
            actor=self.employee,
        )
        self.future_booking = services.create_booking(
            data={
                "car": make_car(plate_number="ORD-002"),
                "client": make_client(name="Adam Alpha"),
                **dict(zip(("start_date", "end_date"), date_range(start_offset=30, duration=2))),
            },
            actor=self.employee,
        )

    def rows(self, **params) -> list[int]:
        response = self.client.get(reverse("bookings:booking_list"), params)
        self.assertEqual(response.status_code, 200)
        return [b.pk for b in response.context["bookings"]]

    def test_newest_booking_is_first_by_default(self):
        """The just-created booking must be at the top, not buried mid-list."""
        self.assertEqual(self.rows()[0], self.future_booking.pk)

    def test_sort_by_nearest_departure_first(self):
        self.assertEqual(self.rows(sort="start_asc")[0], self.today_booking.pk)

    def test_sort_by_furthest_departure_first(self):
        self.assertEqual(self.rows(sort="start_desc")[0], self.future_booking.pk)

    def test_sort_by_client_name(self):
        self.assertEqual(self.rows(sort="client")[0], self.future_booking.pk)  # Adam Alpha

    def test_unknown_sort_falls_back_to_the_default(self):
        self.assertEqual(self.rows(sort="nonsense")[0], self.future_booking.pk)

    def test_sort_selector_is_rendered(self):
        response = self.client.get(reverse("bookings:booking_list"))
        self.assertContains(response, 'name="sort"')
        self.assertContains(response, "Plus récentes d&#x27;abord")

    def test_export_honours_the_sort(self):
        response = self.client.get(
            reverse("bookings:booking_export"), {"format": "csv", "sort": "start_asc"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertLess(body.index("Zoe Zenith"), body.index("Adam Alpha"))
