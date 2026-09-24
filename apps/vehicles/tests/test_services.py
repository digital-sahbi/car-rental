"""Fleet service behaviour: soft delete, audit trail, status sync."""
from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import AuditAction, AuditLog
from apps.core.tests.factories import make_admin, make_car, make_category
from apps.vehicles import services
from apps.vehicles.models import Car, CarImage, CarStatus, Maintenance


def jpeg_bytes() -> bytes:
    """A real (tiny) JPEG so ImageField validation accepts the upload."""
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (12, 12), (30, 60, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


class SoftDeleteTests(TestCase):
    """Requirement 17: cars are archived, never destroyed."""

    def setUp(self):
        self.admin = make_admin()
        self.car = make_car(plate_number="10101-A-1")

    def test_delete_marks_the_row_instead_of_removing_it(self):
        services.delete_car(car=self.car, actor=self.admin)

        self.assertFalse(Car.objects.filter(pk=self.car.pk).exists())
        self.assertTrue(Car.all_objects.filter(pk=self.car.pk).exists())

        stored = Car.all_objects.get(pk=self.car.pk)
        self.assertTrue(stored.is_deleted)
        self.assertIsNotNone(stored.deleted_at)

    def test_restore_brings_the_car_back(self):
        services.delete_car(car=self.car, actor=self.admin)
        stored = Car.all_objects.get(pk=self.car.pk)
        stored.restore()

        self.assertTrue(Car.objects.filter(pk=self.car.pk).exists())
        self.assertIsNone(stored.deleted_at)

    def test_soft_delete_is_audited(self):
        services.delete_car(car=self.car, actor=self.admin)

        entry = AuditLog.objects.filter(model_name="Car", action=AuditAction.DELETE).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.user, self.admin)


class AuditTrailTests(TestCase):
    """Car writes must leave an audit trail."""

    def setUp(self):
        self.admin = make_admin()

    def test_create_is_audited(self):
        car = services.create_car(
            data={
                "name": "Duster",
                "brand": "Dacia",
                "model": "Duster",
                "plate_number": "20202-B-2",
                "category": make_category(),
                "price_per_day": Decimal("480.00"),
                "status": CarStatus.AVAILABLE,
                "seats": 5,
                "year": timezone.localdate().year - 1,
                "mileage": 1000,
            },
            actor=self.admin,
        )
        entry = AuditLog.objects.filter(model_name="Car", action=AuditAction.CREATE).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.object_id, car.pk)
        self.assertEqual(entry.changes["created"]["plate_number"], "20202-B-2")

    def test_update_audits_only_changed_fields(self):
        car = make_car(plate_number="30303-C-3", price_per_day="300.00")
        AuditLog.objects.all().delete()

        services.update_car(
            car=car, data={"price_per_day": Decimal("350.00")}, actor=self.admin
        )

        entry = AuditLog.objects.filter(model_name="Car", action=AuditAction.UPDATE).first()
        self.assertIsNotNone(entry)
        self.assertIn("price_per_day", entry.changes)
        self.assertNotIn("brand", entry.changes)

    def test_update_with_no_changes_logs_nothing(self):
        car = make_car(plate_number="40404-D-4", price_per_day="300.00")
        AuditLog.objects.all().delete()

        services.update_car(car=car, data={"price_per_day": Decimal("300.00")}, actor=self.admin)

        self.assertFalse(AuditLog.objects.filter(action=AuditAction.UPDATE).exists())


class StatusSyncTests(TestCase):
    """``sync_status`` changes status and records the transition."""

    def test_status_change_is_applied_and_audited(self):
        admin = make_admin()
        car = make_car(plate_number="50505-E-5")

        services.sync_status(car=car, status=CarStatus.MAINTENANCE, actor=admin)

        car.refresh_from_db()
        self.assertEqual(car.status, CarStatus.MAINTENANCE)

        entry = AuditLog.objects.filter(model_name="Car", action=AuditAction.UPDATE).first()
        self.assertEqual(entry.changes["status"]["new"], CarStatus.MAINTENANCE)

    def test_same_status_is_a_noop(self):
        car = make_car(plate_number="60606-F-6")
        AuditLog.objects.all().delete()

        services.sync_status(car=car, status=CarStatus.AVAILABLE, actor=None)

        self.assertFalse(AuditLog.objects.exists())


class ValidationTests(TestCase):
    """Model-level guards."""

    def test_price_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            services.create_car(
                data={
                    "name": "X",
                    "brand": "X",
                    "model": "X",
                    "plate_number": "70707-G-7",
                    "category": make_category(),
                    "price_per_day": Decimal("-1.00"),
                    "seats": 5,
                    "year": timezone.localdate().year,
                    "mileage": 0,
                },
                actor=None,
            )

    def test_implausible_year_is_rejected(self):
        with self.assertRaises(ValidationError):
            services.create_car(
                data={
                    "name": "X",
                    "brand": "X",
                    "model": "X",
                    "plate_number": "80808-H-8",
                    "category": make_category(),
                    "price_per_day": Decimal("100.00"),
                    "seats": 5,
                    "year": 1900,
                    "mileage": 0,
                },
                actor=None,
            )

    def test_plate_number_is_unique(self):
        make_car(plate_number="90909-I-9")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Car.objects.create(
                    name="Dup",
                    brand="Dup",
                    model="Dup",
                    plate_number="90909-I-9",
                    category=make_category(),
                    price_per_day=Decimal("100.00"),
                    seats=5,
                    year=timezone.localdate().year,
                    mileage=0,
                )


class MaintenanceTests(TestCase):
    """Logging maintenance keeps the odometer coherent."""

    def test_mileage_is_raised_to_the_service_value(self):
        admin = make_admin()
        car = make_car(plate_number="12121-J-1", mileage=10_000)

        services.create_maintenance(
            car=car,
            data={
                "date": timezone.localdate(),
                "description": "Vidange",
                "cost": Decimal("800.00"),
                "mileage_at_service": 15_000,
            },
            actor=admin,
        )

        car.refresh_from_db()
        self.assertEqual(car.mileage, 15_000)
        self.assertEqual(Maintenance.objects.filter(car=car).count(), 1)

    def test_mileage_is_not_lowered(self):
        admin = make_admin()
        car = make_car(plate_number="13131-K-1", mileage=20_000)

        services.create_maintenance(
            car=car,
            data={
                "date": timezone.localdate(),
                "description": "Contrôle",
                "cost": Decimal("0.00"),
                "mileage_at_service": 5_000,
            },
            actor=admin,
        )

        car.refresh_from_db()
        self.assertEqual(car.mileage, 20_000)


class CarImageTests(TestCase):
    """Gallery invariants.

    "At most one main image per car" is maintained by
    ``services.save_car_images()`` rather than by a database constraint: Django
    evaluates ``Meta.constraints`` during form validation — before the previous
    main can be demoted — so a conditional UniqueConstraint would make
    promoting a photo impossible through the UI.
    """

    def test_multiple_non_main_images_are_allowed(self):
        car = make_car(plate_number="15151-M-1")
        CarImage.objects.create(car=car, image="cars/a.jpg", is_main=False)
        CarImage.objects.create(car=car, image="cars/b.jpg", is_main=False)
        self.assertEqual(car.images.count(), 2)

    def test_gallery_can_hold_several_images(self):
        car = make_car(plate_number="16161-M-2")
        for index in range(4):
            CarImage.objects.create(car=car, image=f"cars/{index}.jpg", is_main=False)
        self.assertEqual(car.images.count(), 4)


class PictureUpdateTests(TestCase):
    """Regression: uploading a picture must not break the audit log.

    ``Car.picture`` is an ``ImageField``, so ``snapshot()`` captures an
    ``ImageFieldFile``. Feeding that straight into the ``changes`` JSONField
    raised ``TypeError: Object of type ImageFieldFile is not JSON
    serializable`` when adding a photo to an existing car.
    """

    def setUp(self):
        self.admin = make_admin()
        self.media_dir = tempfile.mkdtemp(prefix="crm-test-media-")
        self._override = override_settings(MEDIA_ROOT=self.media_dir)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _upload(self, name: str = "nouvelle-photo.jpg") -> SimpleUploadedFile:
        return SimpleUploadedFile(name, jpeg_bytes(), content_type="image/jpeg")

    def test_adding_a_picture_to_an_existing_car_is_audited(self):
        car = make_car(plate_number="17171-O-1")
        self.assertFalse(bool(car.picture))  # no picture yet
        AuditLog.objects.all().delete()

        services.update_car(car=car, data={"picture": self._upload()}, actor=self.admin)

        car.refresh_from_db()
        self.assertTrue(bool(car.picture))

        entry = AuditLog.objects.filter(model_name="Car", action=AuditAction.UPDATE).first()
        self.assertIsNotNone(entry, "the picture change must be recorded in the audit log")
        self.assertIn("picture", entry.changes)
        # Both sides must be plain strings, not file objects.
        self.assertIsInstance(entry.changes["picture"]["new"], str)
        self.assertIn("nouvelle-photo", entry.changes["picture"]["new"])

    def test_replacing_an_existing_picture_is_audited(self):
        car = make_car(plate_number="18181-P-1")
        services.update_car(car=car, data={"picture": self._upload("avant.jpg")}, actor=self.admin)
        AuditLog.objects.all().delete()

        services.update_car(car=car, data={"picture": self._upload("apres.jpg")}, actor=self.admin)

        entry = AuditLog.objects.filter(model_name="Car", action=AuditAction.UPDATE).first()
        self.assertIsNotNone(entry)
        self.assertIn("avant", entry.changes["picture"]["old"])
        self.assertIn("apres", entry.changes["picture"]["new"])


class MainImagePrecedenceTests(TestCase):
    """``Car.main_image`` — one main photo, one defined precedence.

    Two fields claim the role: ``Car.picture`` (the "Photo principale" on the
    car form) and ``CarImage.is_main`` (a gallery photo promoted by hand).

    Rule:

    1. a gallery image explicitly flagged ``is_main`` wins,
    2. otherwise ``Car.picture``,
    3. otherwise the first gallery image (so a gallery-only car still shows one).
    """

    def setUp(self):
        self.admin = make_admin()
        self.media_dir = tempfile.mkdtemp(prefix="crm-main-media-")
        self._override = override_settings(MEDIA_ROOT=self.media_dir)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _with_picture(self, plate: str, name: str = "principale.jpg"):
        car = make_car(plate_number=plate)
        car.picture.save(name, _upload(name), save=True)
        return car

    def test_picture_is_the_main_image_when_the_gallery_has_no_flag(self):
        """Regression: an unflagged gallery photo used to shadow ``picture``."""
        car = self._with_picture("20101-A-1")
        CarImage.objects.create(car=car, image="cars/galerie.jpg", is_main=False)

        self.assertIn("principale", car.main_image.name)

    def test_flagged_gallery_image_wins_over_picture(self):
        car = self._with_picture("20102-A-2")
        CarImage.objects.create(car=car, image="cars/promue.jpg", is_main=True)

        self.assertIn("promue", car.main_image.name)

    def test_gallery_only_car_falls_back_to_the_first_image(self):
        car = make_car(plate_number="20103-A-3")
        CarImage.objects.create(car=car, image="cars/seule.jpg", is_main=False)

        self.assertIn("seule", car.main_image.name)

    def test_car_without_any_image_has_no_main_image(self):
        car = make_car(plate_number="20104-A-4")
        self.assertFalse(car.main_image)

    def test_uploading_a_new_picture_demotes_a_flagged_gallery_image(self):
        """The user's bug: a new main photo must actually become the main photo."""
        car = self._with_picture("20105-A-5", "ancienne.jpg")
        CarImage.objects.create(car=car, image="cars/promue.jpg", is_main=True)

        services.update_car(car=car, data={"picture": _upload("nouvelle.jpg")}, actor=self.admin)

        car.refresh_from_db()
        self.assertFalse(CarImage.objects.filter(car=car, is_main=True).exists())
        self.assertIn("nouvelle", car.main_image.name)

    def test_clearing_the_picture_falls_back_to_the_gallery(self):
        car = self._with_picture("20106-A-6")
        CarImage.objects.create(car=car, image="cars/repli.jpg", is_main=False)

        services.update_car(car=car, data={"picture": False}, actor=self.admin)

        car.refresh_from_db()
        self.assertIn("repli", car.main_image.name)


def _upload(name: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, jpeg_bytes(), content_type="image/jpeg")
