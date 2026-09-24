"""Custom user model: email login, CIN handling, roles."""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts import services
from apps.accounts.forms import EmployeeForm
from apps.accounts.models import Role, User
from apps.core.tests.factories import DEFAULT_PASSWORD, make_admin, make_employee


class UserModelTests(TestCase):
    """The regression that mattered: blank CIN must not collide."""

    def test_two_users_without_a_cin_can_coexist(self):
        services.create_employee(
            data={
                "email": "a@smartrent.ma",
                "first_name": "A",
                "last_name": "One",
                "role": Role.EMPLOYEE,
                "cin": "",
            },
            actor=None,
        )
        # This second insert must not raise a unique-constraint error.
        services.create_employee(
            data={
                "email": "b@smartrent.ma",
                "first_name": "B",
                "last_name": "Two",
                "role": Role.EMPLOYEE,
                "cin": "",
            },
            actor=None,
        )

        self.assertEqual(User.objects.filter(cin__isnull=True).count(), 2)

    def test_duplicate_cin_is_still_rejected(self):
        services.create_employee(
            data={
                "email": "c@smartrent.ma",
                "first_name": "C",
                "last_name": "Three",
                "role": Role.EMPLOYEE,
                "cin": "AA123456",
            },
            actor=None,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create(
                    email="d@smartrent.ma",
                    first_name="D",
                    last_name="Four",
                    cin="AA123456",
                )

    def test_email_is_normalised_by_clean(self):
        user = User(email="  Mixed@Case.MA  ", first_name="X", last_name="Y")
        user.clean()
        self.assertEqual(user.email, "mixed@case.ma")

    def test_full_name_falls_back_to_email(self):
        user = User(email="noname@smartrent.ma")
        self.assertEqual(user.get_full_name(), "")
        self.assertEqual(str(user), "noname@smartrent.ma")

    def test_role_helpers(self):
        self.assertTrue(make_admin().is_admin)
        employee = make_employee()
        self.assertFalse(employee.is_admin)
        self.assertFalse(employee.is_manager)

    def test_whatsapp_link_on_employee(self):
        user = make_employee(whatsapp="+212 661 000 003")
        self.assertEqual(user.whatsapp_link, "https://wa.me/212661000003")


class EmployeeFormTests(TestCase):
    """Password rules differ between create and edit."""

    def test_password_is_required_on_create(self):
        form = EmployeeForm(
            data={
                "first_name": "New",
                "last_name": "Person",
                "email": "new@smartrent.ma",
                "role": Role.EMPLOYEE,
                "is_active": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    def test_mismatched_passwords_are_rejected(self):
        form = EmployeeForm(
            data={
                "first_name": "New",
                "last_name": "Person",
                "email": "new@smartrent.ma",
                "role": Role.EMPLOYEE,
                "is_active": True,
                "password1": "Str0ng-Pass-2026",
                "password2": "Different-Pass-2026",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_weak_password_is_rejected_by_validators(self):
        form = EmployeeForm(
            data={
                "first_name": "New",
                "last_name": "Person",
                "email": "new@smartrent.ma",
                "role": Role.EMPLOYEE,
                "is_active": True,
                "password1": "1234",
                "password2": "1234",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    def test_password_is_optional_when_editing(self):
        employee = make_employee()
        form = EmployeeForm(
            instance=employee,
            data={
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "email": employee.email,
                "role": employee.role,
                "is_active": True,
                "password1": "",
                "password2": "",
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        employee.refresh_from_db()
        self.assertTrue(employee.check_password(DEFAULT_PASSWORD))

    def test_new_password_is_hashed_on_save(self):
        employee = make_employee()
        form = EmployeeForm(
            instance=employee,
            data={
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "email": employee.email,
                "role": employee.role,
                "is_active": True,
                "password1": "Brand-New-Pass-2026",
                "password2": "Brand-New-Pass-2026",
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        employee.refresh_from_db()
        self.assertNotEqual(employee.password, "Brand-New-Pass-2026")
        self.assertTrue(employee.check_password("Brand-New-Pass-2026"))


class EmployeeCrewViewTests(TestCase):
    """The admin-only CRUD screens."""

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)

    def test_admin_can_create_an_employee(self):
        response = self.client.post(
            reverse("accounts:employee_add"),
            {
                "first_name": "Nadia",
                "last_name": "Alaoui",
                "email": "nadia@smartrent.ma",
                "telephone": "+212 600 000 000",
                "role": Role.EMPLOYEE,
                "is_active": True,
                "password1": "Str0ng-Pass-2026",
                "password2": "Str0ng-Pass-2026",
            },
        )
        self.assertEqual(response.status_code, 302)

        created = User.objects.get(email="nadia@smartrent.ma")
        self.assertEqual(created.role, Role.EMPLOYEE)
        self.assertTrue(created.check_password("Str0ng-Pass-2026"))

    def test_toggle_deactivates_and_reactivates(self):
        employee = make_employee()

        self.client.post(reverse("accounts:employee_toggle", args=[employee.pk]))
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)

        self.client.post(reverse("accounts:employee_toggle", args=[employee.pk]))
        employee.refresh_from_db()
        self.assertTrue(employee.is_active)

    def test_toggle_on_a_missing_user_returns_404_not_500(self):
        response = self.client.post(reverse("accounts:employee_toggle", args=[999_999]))
        self.assertEqual(response.status_code, 404)
