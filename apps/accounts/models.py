"""Custom user model for the internal CRM.

Login is by email. Roles drive access control via
``apps.core.mixins.RoleRequiredMixin``.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class Role(models.TextChoices):
    ADMIN = "ADMIN", _("Administrateur")
    MANAGER = "MANAGER", _("Responsable")
    EMPLOYEE = "EMPLOYEE", _("Employé")


class User(AbstractUser):
    """Employee account. ``email`` is the unique login field."""

    # Drop username in favour of email as the username field.
    username = None  # type: ignore[assignment]
    email = models.EmailField(_("email"), unique=True)

    first_name = models.CharField(_("prénom"), max_length=150)
    last_name = models.CharField(_("nom"), max_length=150)

    telephone = models.CharField(_("téléphone"), max_length=30, blank=True)
    whatsapp = models.CharField(_("WhatsApp"), max_length=30, blank=True)
    cin = models.CharField(
        _("CIN"),
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text=_("Carte d'Identité Nationale (identifiant unique)."),
    )
    role = models.CharField(
        _("rôle"),
        max_length=16,
        choices=Role.choices,
        default=Role.EMPLOYEE,
        db_index=True,
    )

    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)
    notifications_seen_at = models.DateTimeField(
        _("notifications consultées le"),
        null=True,
        blank=True,
        help_text=_("Dernière ouverture du panneau de notifications (badge)."),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]  # for createsuperuser

    objects = UserManager()

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        ordering = ("last_name", "first_name")

    def __str__(self) -> str:
        return self.get_full_name() or self.email

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def clean(self) -> None:
        """Normalise ``email`` and blank ``cin``.

        ``cin`` is unique but optional: storing ``""`` would make a second
        employee without a CIN collide on the unique index, so blanks become
        ``NULL`` (which SQL treats as distinct).
        """
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()
        if not self.cin:
            self.cin = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_manager(self) -> bool:
        return self.role == Role.MANAGER

    @property
    def whatsapp_link(self) -> str:
        """``https://wa.me/<number>`` deep link (digits only), or ''."""
        digits = "".join(ch for ch in self.whatsapp or "" if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ""