"""Header notification bell: feed, unread badge and read state.

* managers/admins → the edit-request approval queue,
* employees → activity on the bookings they may see,
* "unread" → created after ``User.notifications_seen_at``.
"""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.bookings import services as booking_services
from apps.core import notifications
from apps.core.models import AuditLog
from apps.core.tests.factories import (
    date_range,
    make_admin,
    make_car,
    make_client,
    make_employee,
    make_manager,
)


def booking_data(plate: str, client_name: str, *, start_offset: int = 1):
    return {
        "car": make_car(plate_number=plate),
        "client": make_client(name=client_name),
        **dict(zip(("start_date", "end_date"), date_range(start_offset=start_offset, duration=2))),
    }


class EmployeeFeedTests(TestCase):
    """An employee's feed covers only their own bookings."""

    def setUp(self):
        self.employee = make_employee(first_name="Karim")
        self.colleague = make_employee(first_name="Nadia")
        self.manager = make_manager()
        self.admin = make_admin()

        self.mine = booking_services.create_booking(
            data=booking_data("NOT-001", "My Client"), actor=self.employee
        )
        self.theirs = booking_services.create_booking(
            data=booking_data("NOT-002", "Their Client", start_offset=10), actor=self.colleague
        )

    def test_feed_contains_my_booking(self):
        items = notifications.notifications_for(self.employee)
        self.assertTrue(items)
        self.assertTrue(all("My Client" in item.detail for item in items))

    def test_feed_excludes_a_colleagues_booking(self):
        items = notifications.notifications_for(self.employee)
        self.assertFalse(any("Their Client" in item.detail for item in items))

    def test_feed_links_to_the_booking(self):
        item = notifications.notifications_for(self.employee)[0]
        self.assertEqual(item.url, reverse("bookings:booking_detail", args=[self.mine.pk]))
        self.assertEqual(item.kind, "audit")

    def test_managers_get_the_approval_queue_not_booking_activity(self):
        """Managers care about what needs approving, not what was created."""
        self.assertEqual(notifications.notifications_for(self.manager), [])

    def test_anonymous_user_has_no_feed(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(notifications.notifications_for(AnonymousUser()), [])


class ManagerFeedTests(TestCase):
    """Managers see pending edit requests."""

    def setUp(self):
        self.employee = make_employee()
        self.manager = make_manager()
        self.booking = booking_services.create_booking(
            data=booking_data("NOT-010", "Queue Client"), actor=self.employee
        )

    def _submit(self, reason: str = "Prolonger la location"):
        return booking_services.submit_edit_request(
            booking=self.booking,
            requested_by=self.employee,
            reason=reason,
            proposed_changes={"notes": "ok"},
        )

    def test_pending_request_appears_in_the_feed(self):
        self._submit()

        items = notifications.notifications_for(self.manager)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "edit_request")
        self.assertIn(self.booking.client.name, items[0].detail)
        self.assertEqual(items[0].url, reverse("bookings:edit_request_list"))

    def test_reviewed_request_leaves_the_feed(self):
        request_item = self._submit()
        booking_services.review_edit_request(
            edit_request=request_item, approve=True, reviewer=self.manager
        )

        self.assertEqual(notifications.notifications_for(self.manager), [])

    def test_admins_see_the_same_queue(self):
        self._submit()
        admin = make_admin()
        self.assertEqual(len(notifications.notifications_for(admin)), 1)


class UnreadBadgeTests(TestCase):
    """The badge counts items that arrived since the panel was last opened."""

    def setUp(self):
        self.employee = make_employee()
        self.booking = booking_services.create_booking(
            data=booking_data("NOT-020", "Badge Client"), actor=self.employee
        )

    def test_counts_everything_when_never_opened(self):
        self.assertIsNone(self.employee.notifications_seen_at)
        self.assertEqual(notifications.unread_notification_count(self.employee), 1)

    def test_resets_once_opened(self):
        notifications.mark_notifications_seen(self.employee)
        self.employee.refresh_from_db()

        self.assertEqual(notifications.unread_notification_count(self.employee), 0)

    def test_counts_only_items_after_the_last_open(self):
        """Items recorded before the last open must not be counted again."""
        # Backdate what already exists so the boundary is unambiguous, then
        # treat it all as "seen".
        AuditLog.objects.update(timestamp=timezone.now() - timezone.timedelta(hours=1))
        notifications.mark_notifications_seen(self.employee)
        self.employee.refresh_from_db()

        booking_services.create_booking(
            data=booking_data("NOT-021", "Fresh Client", start_offset=20), actor=self.employee
        )

        self.assertEqual(notifications.unread_notification_count(self.employee), 1)

    def test_anonymous_user_has_no_badge(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(notifications.unread_notification_count(AnonymousUser()), 0)

    def test_mark_seen_is_persisted(self):
        notifications.mark_notifications_seen(self.employee)
        self.employee.refresh_from_db()
        self.assertIsNotNone(self.employee.notifications_seen_at)


class MarkSeenEndpointTests(TestCase):
    """The bell posts to this endpoint when it is opened."""

    def setUp(self):
        self.employee = make_employee()
        self.client.force_login(self.employee)

    def test_post_marks_seen_and_reports_zero(self):
        response = self.client.post(reverse("core:notifications_seen"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"unread": 0})
        self.employee.refresh_from_db()
        self.assertIsNotNone(self.employee.notifications_seen_at)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse("core:notifications_seen")).status_code, 405)

    def test_anonymous_user_is_redirected(self):
        self.client.logout()
        response = self.client.post(reverse("core:notifications_seen"))
        self.assertEqual(response.status_code, 302)


class BellRenderingTests(TestCase):
    """The bell, its badge and the panel render in the header."""

    def setUp(self):
        self.employee = make_employee()
        self.booking = booking_services.create_booking(
            data=booking_data("NOT-030", "Bell Client"), actor=self.employee
        )
        self.client.force_login(self.employee)

    def test_bell_renders_with_a_badge(self):
        response = self.client.get(reverse("core:dashboard"))

        self.assertContains(response, "data-notif")
        self.assertContains(response, "notif__badge")
        self.assertContains(response, "data-notif-seen-url")
        self.assertEqual(response.context["unread_notifications"], 1)

    def test_panel_lists_the_latest_items(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "Bell Client")

    def test_badge_is_hidden_after_opening(self):
        notifications.mark_notifications_seen(self.employee)

        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.context["unread_notifications"], 0)
        self.assertContains(response, "hidden")

    def test_login_page_has_no_bell(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:login"))
        self.assertNotContains(response, "data-notif")

    def test_history_link_points_to_the_audit_log_for_an_admin(self):
        admin = make_admin()
        self.client.force_login(admin)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.context["history_url"], reverse("core:audit_log"))

    def test_history_link_points_to_the_activity_page_for_an_employee(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.context["history_url"], reverse("core:activity"))


class ActivityPageTests(TestCase):
    """The scoped history page."""

    def setUp(self):
        self.employee = make_employee(first_name="Karim")
        self.colleague = make_employee(first_name="Nadia")
        self.mine = booking_services.create_booking(
            data=booking_data("NOT-040", "Mine Client"), actor=self.employee
        )
        self.theirs = booking_services.create_booking(
            data=booking_data("NOT-041", "Theirs Client", start_offset=15), actor=self.colleague
        )

    def test_employee_only_sees_actions_about_their_own_bookings(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("core:activity"))

        self.assertEqual(response.status_code, 200)
        object_ids = {entry.object_id for entry in response.context["entries"]}
        self.assertIn(self.mine.pk, object_ids)
        self.assertNotIn(self.theirs.pk, object_ids)

    def test_manager_sees_the_bookings_they_may_access(self):
        manager = make_manager()
        self.client.force_login(manager)
        response = self.client.get(reverse("core:activity"))

        object_ids = {entry.object_id for entry in response.context["entries"]}
        self.assertIn(self.theirs.pk, object_ids)

    def test_action_filter_is_applied(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("core:activity"), {"action": "UPDATE"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            all(entry.action == "UPDATE" for entry in response.context["entries"])
        )

    def test_anonymous_user_is_redirected(self):
        response = self.client.get(reverse("core:activity"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_audit_log_remains_admin_only(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("core:audit_log")).status_code, 403)
