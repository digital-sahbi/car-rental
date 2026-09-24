"""Vehicle views: the car form's picture handling.

Regression cover for a subtle contract in ``FileField.save_form_data``:

* ``None``            → "no change", keep the existing file
* ``False`` / ``""``  → "clear the file"
* an ``UploadedFile`` → store the new file

Applying these values with a bare ``setattr`` stores the raw boolean/None in
``instance.__dict__``, which then explodes in ``FileField.pre_save`` with
``AttributeError: 'bool' object has no attribute 'name'`` — or silently wipes
the photo.
"""
from __future__ import annotations

import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.tests.factories import make_admin, make_car, make_category
from apps.vehicles.models import Car, CarImage, CarStatus, Maintenance

from .test_services import jpeg_bytes


class CarPictureFormFlowTests(TestCase):
    """Drive the real ``CarUpdateView`` the way a browser does."""

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)

        self.media_dir = tempfile.mkdtemp(prefix="crm-view-media-")
        self._override = override_settings(MEDIA_ROOT=self.media_dir)
        self._override.enable()

        self.car = make_car(plate_number="19191-Q-1")
        self.car.picture.save("original.jpg", _upload("original.jpg"), save=True)

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    @property
    def url(self) -> str:
        return reverse("vehicles:car_edit", args=[self.car.pk])

    def payload(self, **overrides) -> dict:
        """A complete, valid car form submission (no file, no clear tick)."""
        data = {
            "name": self.car.name,
            "brand": self.car.brand,
            "model": self.car.model,
            "plate_number": self.car.plate_number,
            "category": self.car.category.pk,
            "price_per_day": str(self.car.price_per_day),
            "status": CarStatus.AVAILABLE,
            "fuel_type": "diesel",
            "transmission": "manual",
            "seats": 5,
            "year": self.car.year,
            "mileage": 1000,
            "description": "",
            # inline gallery formset
            "images-TOTAL_FORMS": "0",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    # -- the reported crash ------------------------------------------------

    def test_clearing_the_picture_does_not_crash(self):
        response = self.client.post(self.url, self.payload(**{"picture-clear": "on"}))

        self.assertEqual(
            response.status_code, 302, "clearing the photo must redirect, not 500"
        )
        self.car.refresh_from_db()
        self.assertFalse(self.car.picture, "the photo should have been cleared")

    def test_replacing_the_picture_works(self):
        response = self.client.post(
            self.url,
            {**self.payload(), "picture": _upload("replacement.jpg")},
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertIn("replacement", self.car.picture.name)

    # -- the silent data-loss sibling --------------------------------------

    def test_resaving_without_touching_the_picture_keeps_it(self):
        response = self.client.post(self.url, self.payload())

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertTrue(self.car.picture, "the existing photo must survive a re-save")
        self.assertIn("original", self.car.picture.name)

    def test_saving_other_fields_still_works(self):
        response = self.client.post(self.url, self.payload(mileage=42_000))

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 42_000)
        self.assertTrue(self.car.picture)

    def test_overbooking_style_validation_errors_keep_the_picture(self):
        """An invalid submit must not damage the stored photo."""
        response = self.client.post(self.url, self.payload(plate_number=""))

        self.assertEqual(response.status_code, 200)  # re-rendered with errors
        self.car.refresh_from_db()
        self.assertTrue(self.car.picture)

    # -- main-picture behaviour the user actually sees ---------------------

    def test_detail_page_shows_the_main_picture_even_with_a_gallery(self):
        """Regression: the main picture must render, not be hidden by the gallery."""
        CarImage.objects.create(car=self.car, image="cars/galerie.jpg", is_main=False)

        response = self.client.get(reverse("vehicles:car_detail", args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "original")  # the Car.picture filename

    def test_uploading_a_new_main_picture_from_the_form_wins(self):
        CarImage.objects.create(car=self.car, image="cars/promue.jpg", is_main=True)

        response = self.client.post(
            self.url,
            {**self.payload(), "picture": _upload("photo-principale.jpg")},
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertFalse(
            CarImage.objects.filter(car=self.car, is_main=True).exists(),
            "a new main photo must demote the flagged gallery image",
        )
        self.assertIn("photo-principale", self.car.main_image.name)

        detail = self.client.get(reverse("vehicles:car_detail", args=[self.car.pk]))
        self.assertContains(detail, "photo-principale")

    def test_adding_a_second_main_gallery_image_does_not_crash(self):
        """The per-car unique constraint on is_main must not surface as a 500.

        ``INITIAL_FORMS=0`` simulates adding a brand-new gallery row flagged as
        main while an older main row already exists in the database.
        """
        CarImage.objects.create(car=self.car, image="cars/ancienne-main.jpg", is_main=True)

        payload = self.payload()
        payload.update(
            {
                "images-TOTAL_FORMS": "1",
                "images-INITIAL_FORMS": "0",
                "images-0-image": _upload("nouvelle-main.jpg"),
                "images-0-is_main": "on",
            }
        )
        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, 302)
        mains = CarImage.objects.filter(car=self.car, is_main=True)
        self.assertEqual(mains.count(), 1, "exactly one gallery image may be main")


def _upload(name: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, jpeg_bytes(), content_type="image/jpeg")


class MaintenanceFormFlowTests(TestCase):
    """Logging a maintenance intervention through the real form.

    Regression: ``MaintenanceCreateView.form_valid`` writes through the service
    layer and never set ``self.object``, so Django 6.1's
    ``ModelFormMixin.get_success_url`` (``self.success_url.format(**self.object.__dict__)``)
    raised ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
    """

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.car = make_car(plate_number="MNT-001", mileage=10_000)

    @property
    def url(self) -> str:
        return reverse("vehicles:maintenance_add")

    def payload(self, **overrides) -> dict:
        data = {
            "car": self.car.pk,
            "date": "2026-09-20",
            "description": "Vidange + filtres",
            "cost": "800.00",
            "mileage_at_service": 20_000,
            "next_service_date": "2027-03-20",
        }
        data.update(overrides)
        return data

    def test_adding_a_maintenance_record_redirects(self):
        response = self.client.post(self.url, self.payload())

        self.assertEqual(
            response.status_code, 302, "saving must redirect, not raise a 500"
        )
        self.assertEqual(response["Location"], reverse("vehicles:maintenance_list"))
        self.assertEqual(Maintenance.objects.count(), 1)

    def test_the_record_is_saved_with_the_right_values(self):
        self.client.post(self.url, self.payload())

        record = Maintenance.objects.get()
        self.assertEqual(record.car, self.car)
        self.assertEqual(str(record.date), "2026-09-20")
        self.assertEqual(str(record.cost), "800.00")
        self.assertEqual(record.created_by, self.admin)

    def test_the_odometer_and_status_follow_the_intervention(self):
        self.client.post(self.url, self.payload())

        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 20_000)

    def test_optional_fields_may_be_left_out(self):
        payload = self.payload()
        payload.pop("mileage_at_service")
        payload.pop("next_service_date")

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Maintenance.objects.count(), 1)

    def test_invalid_submission_is_re_rendered(self):
        response = self.client.post(self.url, self.payload(description=""))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Maintenance.objects.count(), 0)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])


class CarCreateFormFlowTests(TestCase):
    """Adding a car through the form.

    Shares the ``self.object`` pattern that broke ``MaintenanceCreateView``, so
    it is guarded explicitly rather than left to chance.
    """

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)
        self.category = make_category()

    def payload(self, **overrides) -> dict:
        data = {
            "name": "Logan",
            "brand": "Dacia",
            "model": "Logan",
            "plate_number": "NEW-001",
            "category": self.category.pk,
            "price_per_day": "300.00",
            "status": CarStatus.AVAILABLE,
            "fuel_type": "diesel",
            "transmission": "manual",
            "seats": 5,
            "year": 2024,
            "mileage": 0,
            "description": "",
            # inline gallery formset
            "images-TOTAL_FORMS": "0",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_adding_a_car_redirects_and_saves(self):
        response = self.client.post(reverse("vehicles:car_add"), self.payload())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("vehicles:car_list"))
        self.assertTrue(Car.objects.filter(plate_number="NEW-001").exists())

    def test_a_new_car_is_audited(self):
        from apps.core.models import AuditAction, AuditLog

        self.client.post(reverse("vehicles:car_add"), self.payload())

        self.assertTrue(
            AuditLog.objects.filter(model_name="Car", action=AuditAction.CREATE).exists()
        )

    def test_invalid_submission_is_re_rendered(self):
        response = self.client.post(reverse("vehicles:car_add"), self.payload(plate_number=""))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Car.objects.filter(plate_number="").exists())
