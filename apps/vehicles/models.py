"""Vehicles models: the fleet (parc).

``Car`` replaces the old ``bicycle.Car``. The old model had 5 fields; this one
carries the full rental record (plate, category, status, fuel, transmission,
seats, year, mileage) plus soft delete and audit columns.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import AuditedModel, SoftDeleteModel, TimeStampedModel


def validate_year(value: int) -> None:
    """A vehicle year must be plausible (1990 → next year)."""
    current = timezone.localdate().year
    if value < 1990 or value > current + 1:
        raise ValidationError(
            _("Année invalide : attendu entre 1990 et %(max)s.") % {"max": current + 1}
        )


class CarCategory(models.Model):
    """Rental category — economy, SUV, luxury, minibus…"""

    class Name(models.TextChoices):
        ECONOMY = "economy", _("Économique")
        COMPACT = "compact", _("Compacte")
        FAMILY = "family", _("Familiale")
        SUV = "suv", _("SUV / 4x4")
        ELECTRIC = "electric", _("Électrique / Hybride")
        LUXURY = "luxury", _("Luxe")
        MINIBUS = "minibus", _("Minibus")

    name = models.CharField(
        _("catégorie"),
        max_length=20,
        choices=Name.choices,
        unique=True,
    )
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("catégorie de véhicule")
        verbose_name_plural = _("catégories de véhicules")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.get_name_display()


class CarStatus(models.TextChoices):
    AVAILABLE = "available", _("Disponible")
    RENTED = "rented", _("Loué")
    MAINTENANCE = "maintenance", _("En maintenance")
    OUT_OF_SERVICE = "out_of_service", _("Hors service")


class FuelType(models.TextChoices):
    DIESEL = "diesel", _("Diesel")
    PETROL = "petrol", _("Essence")
    ELECTRIC = "electric", _("Électrique")
    HYBRID = "hybrid", _("Hybride")


class Transmission(models.TextChoices):
    MANUAL = "manual", _("Manuelle")
    AUTOMATIC = "automatic", _("Automatique")


class Car(TimeStampedModel, AuditedModel, SoftDeleteModel):
    """A rental vehicle.

    ``status`` is maintained by :mod:`apps.vehicles.services` — never set it
    blindly from a view.
    """

    name = models.CharField(_("nom"), max_length=100)
    brand = models.CharField(_("marque"), max_length=100)
    model = models.CharField(_("modèle"), max_length=100)
    plate_number = models.CharField(_("immatriculation"), max_length=32, unique=True, db_index=True)
    category = models.ForeignKey(
        CarCategory,
        on_delete=models.PROTECT,
        related_name="cars",
        verbose_name=_("catégorie"),
    )
    price_per_day = models.DecimalField(
        _("prix / jour"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    picture = models.ImageField(_("photo principale"), upload_to="cars/", null=True, blank=True)
    status = models.CharField(
        _("état"),
        max_length=20,
        choices=CarStatus.choices,
        default=CarStatus.AVAILABLE,
        db_index=True,
    )
    fuel_type = models.CharField(
        _("carburant"), max_length=16, choices=FuelType.choices, default=FuelType.DIESEL
    )
    transmission = models.CharField(
        _("boîte"), max_length=16, choices=Transmission.choices, default=Transmission.MANUAL
    )
    seats = models.PositiveSmallIntegerField(_("places"), default=5, validators=[MinValueValidator(1)])
    year = models.PositiveSmallIntegerField(_("année"), validators=[validate_year])
    mileage = models.PositiveIntegerField(_("kilométrage"), default=0)
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("véhicule")
        verbose_name_plural = _("véhicules")
        ordering = ("brand", "model", "plate_number")
        base_manager_name = "all_objects"
        indexes = [
            models.Index(fields=["status", "category"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_per_day__gte=0),
                name="car_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.brand} {self.model} ({self.plate_number})"

    @property
    def full_name(self) -> str:
        return f"{self.brand} {self.model}"

    @property
    def is_available(self) -> bool:
        return self.status == CarStatus.AVAILABLE

    @property
    def main_image(self):
        """The vehicle's main photo.

        Two fields can claim that role, so the precedence is explicit:

        1. a gallery image explicitly promoted with ``is_main``,
        2. ``picture`` — the "Photo principale" uploaded on the car form,
        3. the first gallery image, so a gallery-only car still shows one.

        Step 2 used to come last, which meant uploading a new main photo had no
        visible effect as soon as the car had any gallery image.
        """
        if self.pk:
            flagged = self.images.filter(is_main=True).first()
            if flagged:
                return flagged.image
        if self.picture:
            return self.picture
        if self.pk:
            first = self.images.first()
            if first:
                return first.image
        return None

    def clean(self) -> None:
        super().clean()
        if self.year:
            validate_year(self.year)


class CarImage(models.Model):
    """Extra gallery pictures for a car (requirement: multiple pictures).

    ``is_main`` marks the gallery photo promoted to be the car's main image.
    "At most one main per car" is maintained by
    :func:`apps.vehicles.services.save_car_images`, **not** by a database
    constraint: Django evaluates ``Meta.constraints`` during form validation,
    i.e. before the outgoing main image can be demoted, so a conditional
    UniqueConstraint here would make promoting a photo impossible through the
    UI (partial unique indexes cannot be deferred on any backend).
    """

    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name=_("véhicule"),
    )
    image = models.ImageField(_("image"), upload_to="cars/")
    is_main = models.BooleanField(_("image principale"), default=False, db_index=True)
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)

    class Meta:
        verbose_name = _("photo de véhicule")
        verbose_name_plural = _("photos de véhicules")
        ordering = ("-is_main", "id")

    def __str__(self) -> str:
        return f"{self.car.plate_number} — {'principale' if self.is_main else self.pk}"


class Maintenance(TimeStampedModel):
    """A maintenance / service intervention on a car."""

    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name="maintenances",
        verbose_name=_("véhicule"),
    )
    date = models.DateField(_("date"), default=timezone.localdate)
    description = models.TextField(_("description"))
    cost = models.DecimalField(
        _("coût"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    mileage_at_service = models.PositiveIntegerField(_("kilométrage au service"), null=True, blank=True)
    next_service_date = models.DateField(_("prochain service"), null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenances_created",
        verbose_name=_("créé par"),
    )

    class Meta:
        verbose_name = _("maintenance")
        verbose_name_plural = _("maintenances")
        ordering = ("-date",)
        indexes = [models.Index(fields=["car", "-date"])]

    def __str__(self) -> str:
        return f"{self.car.plate_number} — {self.date:%d/%m/%Y}"

    def clean(self) -> None:
        super().clean()
        if self.next_service_date and self.date and self.next_service_date < self.date:
            raise ValidationError(
                {"next_service_date": _("Le prochain service doit suivre la date d'intervention.")}
            )
