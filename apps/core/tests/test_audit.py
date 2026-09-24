"""Audit-log behaviour."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from apps.core.models import AuditAction, AuditLog
from apps.core.services import diff, log_action
from apps.core.tests.factories import make_admin


class AuditLogImmutabilityTests(TestCase):
    """The journal must be append-only."""

    def test_entry_is_created_with_actor_and_ip(self):
        user = make_admin()
        request = RequestFactory().post("/")
        request.user = user
        request.META["REMOTE_ADDR"] = "10.1.2.3"

        entry = log_action(action=AuditAction.CREATE, instance=user, request=request)

        self.assertEqual(entry.user, user)
        self.assertEqual(entry.model_name, "User")
        self.assertEqual(entry.object_id, user.pk)
        self.assertEqual(entry.ip_address, "10.1.2.3")

    def test_update_of_existing_entry_is_refused(self):
        entry = AuditLog.objects.create(action=AuditAction.CREATE, model_name="Car")
        entry.object_repr = "tampered"

        with self.assertRaises(ValidationError):
            entry.save()

    def test_forwarded_header_wins_over_remote_addr(self):
        user = make_admin()
        request = RequestFactory().post("/")
        request.user = user
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.7, 10.0.0.1"

        entry = log_action(action=AuditAction.LOGIN, instance=user, request=request)

        self.assertEqual(entry.ip_address, "203.0.113.7")

    def test_decimal_changes_are_json_serialisable(self):
        """``changes`` must survive the JSONField round-trip."""
        from decimal import Decimal

        from apps.core.tests.factories import make_car

        car = make_car(price_per_day="310.50")
        entry = log_action(
            action=AuditAction.UPDATE,
            instance=car,
            changes={"price_per_day": {"old": Decimal("300.00"), "new": Decimal("310.50")}},
        )
        entry.refresh_from_db()

        self.assertEqual(entry.changes["price_per_day"]["new"], "310.50")


class DiffTests(TestCase):
    """``diff`` reports only real changes."""

    def test_only_changed_fields_are_returned(self):
        result = diff({"a": 1, "b": 2}, {"a": 1, "b": 9})
        self.assertEqual(result, {"b": {"old": 2, "new": 9}})
