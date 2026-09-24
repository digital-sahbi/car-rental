"""Core models.

Layers:

* Shared abstract bases — :class:`TimeStampedModel`, :class:`AuditedModel`,
  :class:`SoftDeleteModel` — used by every business app.
* CRM-wide singletons & lookup tables — :class:`CompanySettings`,
  :class:`Promotion`.
* :class:`AuditLog` — the immutable action journal.

The abstract bases deliberately do **not** share a common parent: a diamond
inheritance would make Django copy the same field twice and raise a clash
error. Instead a concrete model composes them::

    class Car(TimeStampedModel, AuditedModel, SoftDeleteModel):
        ...
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# ---------------------------------------------------------------------------
# Shared abstract bases
# ---------------------------------------------------------------------------


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet for soft-deletable models."""

    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=False)

    def dead(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=True)

    def delete(self) -> int:
        """Soft-delete the whole queryset."""
        return super().update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Really remove the rows. Only for tests / GDPR-style erasure."""
        return super().delete()


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Default manager: hides soft-deleted rows."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(is_deleted=False)


class TimeStampedModel(models.Model):
    """Adds ``created_at`` / ``updated_at`` (requirement 6)."""

    created_at = models.DateTimeField(_("créé le"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        abstract = True


class AuditedModel(models.Model):
    """Adds ``created_by`` / ``updated_by`` (requirement 6)."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("créé par"),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("modifié par"),
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Never hard-delete (requirement 17).

    ``objects`` hides deleted rows, ``all_objects`` exposes everything.
    Concrete models must set ``Meta.base_manager_name = "all_objects"`` so
    that following a ForeignKey to a soft-deleted row still works (history
    must stay readable).
    """

    is_deleted = models.BooleanField(_("supprimé"), default=False, db_index=True)
    deleted_at = models.DateTimeField(_("supprimé le"), null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(
        self,
        using: Optional[str] = None,
        keep_parents: bool = False,
        *,
        hard: bool = False,
    ):
        """Soft-delete by default; ``hard=True`` really removes the row."""
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])
        return 1, {self._meta.label: 1}

    def restore(self) -> None:
        """Undo a soft delete."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditAction(models.TextChoices):
    CREATE = "CREATE", _("Création")
    UPDATE = "UPDATE", _("Modification")
    DELETE = "DELETE", _("Suppression")
    LOGIN = "LOGIN", _("Connexion")
    LOGOUT = "LOGOUT", _("Déconnexion")
    APPROVE = "APPROVE", _("Approbation")
    REJECT = "REJECT", _("Rejet")
    PRINT = "PRINT", _("Impression")


class AuditLog(models.Model):
    """Immutable record of every meaningful action in the CRM."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        verbose_name=_("utilisateur"),
        help_text=_("Null pour les actions système."),
    )
    action = models.CharField(max_length=16, choices=AuditAction.choices, verbose_name=_("action"))
    model_name = models.CharField(max_length=64, verbose_name=_("modèle"))
    object_id = models.IntegerField(null=True, blank=True, verbose_name=_("ID objet"))
    object_repr = models.CharField(max_length=255, blank=True, verbose_name=_("représentation"))
    changes = models.JSONField(default=dict, blank=True, verbose_name=_("changements"))
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("adresse IP"))
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_("horodatage"))

    class Meta:
        verbose_name = _("journal d'audit")
        verbose_name_plural = _("journal d'audit")
        ordering = ("-timestamp",)
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["action", "-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.action} {self.model_name}#{self.object_id}"

    def save(self, *args: Any, **kwargs: Any):
        """Append-only: updates are refused."""
        if self.pk is not None:
            raise ValidationError(_("Le journal d'audit est immuable."))
        return super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Company settings (singleton)
# ---------------------------------------------------------------------------


class CompanySettings(models.Model):
    """Single row (pk=1) holding branding + legal data used on invoices."""

    company_name = models.CharField(_("raison sociale"), max_length=200)
    logo = models.ImageField(_("logo"), upload_to="company/", null=True, blank=True)
    address = models.TextField(_("adresse"), blank=True)
    phone = models.CharField(_("téléphone"), max_length=40, blank=True)
    email = models.EmailField(_("email"), blank=True)
    website = models.URLField(_("site web"), blank=True)

    # Moroccan company identifiers.
    ice = models.CharField(
        _("ICE"), max_length=40, blank=True, help_text=_("Identifiant Commun de l'Entreprise")
    )
    rc = models.CharField(_("RC"), max_length=40, blank=True, help_text=_("Registre du Commerce"))
    patente = models.CharField(_("patente"), max_length=40, blank=True)
    if_number = models.CharField(_("IF"), max_length=40, blank=True, help_text=_("Identifiant Fiscal"))

    bank_details = models.TextField(_("coordonnées bancaires"), blank=True)
    default_vat = models.DecimalField(
        _("TVA par défaut (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    invoice_footer = models.TextField(_("pied de facture"), blank=True)
    default_language = models.CharField(
        _("langue par défaut"),
        max_length=5,
        choices=[(code, name) for code, name in settings.LANGUAGES],
        default=settings.LANGUAGE_CODE,
    )

    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        verbose_name = _("paramètres de l'entreprise")
        verbose_name_plural = _("paramètres de l'entreprise")

    def __str__(self) -> str:
        return self.company_name or _("Paramètres de l'entreprise")

    def save(self, *args: Any, **kwargs: Any):
        """Enforce the singleton (always pk=1)."""
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "CompanySettings":
        """Return the singleton, creating a blank one if needed."""
        obj, _created = cls.objects.get_or_create(
            pk=1,
            defaults={"company_name": "Smart Rent Car"},
        )
        return obj


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


class DiscountType(models.TextChoices):
    PERCENTAGE = "percentage", _("Pourcentage")
    FIXED = "fixed", _("Montant fixe")


class Promotion(models.Model):
    """Discount code applied when an invoice is issued."""

    code = models.CharField(_("code"), max_length=32, unique=True)
    description = models.CharField(_("description"), max_length=255, blank=True)
    discount_type = models.CharField(
        _("type de remise"),
        max_length=16,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE,
    )
    discount_value = models.DecimalField(
        _("valeur"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    valid_from = models.DateField(_("valide du"), null=True, blank=True)
    valid_to = models.DateField(_("valide au"), null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_promotions",
        verbose_name=_("créé par"),
    )
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        verbose_name = _("promotion")
        verbose_name_plural = _("promotions")
        ordering = ("code",)

    def __str__(self) -> str:
        return self.code

    def clean(self) -> None:
        super().clean()
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError({"valid_to": _("La date de fin doit suivre la date de début.")})
        if self.discount_type == DiscountType.PERCENTAGE and self.discount_value > 100:
            raise ValidationError({"discount_value": _("Un pourcentage ne peut dépasser 100.")})

    @property
    def is_valid_now(self) -> bool:
        """True when active and today falls inside the validity window."""
        if not self.is_active:
            return False
        today = timezone.localdate()
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_to and today > self.valid_to:
            return False
        return True

    def discount_for(self, amount: Decimal) -> Decimal:
        """Discount (never negative, never above ``amount``) for ``amount``."""
        if amount <= 0:
            return Decimal("0.00")
        if self.discount_type == DiscountType.PERCENTAGE:
            value = amount * self.discount_value / Decimal("100")
        else:
            value = self.discount_value
        return min(value, amount).quantize(Decimal("0.01"))
