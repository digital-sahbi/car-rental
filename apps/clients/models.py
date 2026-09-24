"""Client model.

Replaces nothing from the legacy project (bookings used to hang off the auth
User directly) — this is genuinely new: the CRM now tracks the *customer*
separately from the *employee* who takes the booking.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AuditedModel, SoftDeleteModel, TimeStampedModel

MOROCCO = "Maroc"


class Client(TimeStampedModel, AuditedModel, SoftDeleteModel):
    """A rental customer (local or international)."""

    name = models.CharField(_("nom complet"), max_length=150, db_index=True)
    telephone = models.CharField(_("téléphone"), max_length=40, db_index=True)
    whatsapp = models.CharField(_("WhatsApp"), max_length=40, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.CharField(_("adresse"), max_length=255, blank=True)
    country = models.CharField(_("pays"), max_length=80, default=MOROCCO, db_index=True)
    id_document = models.CharField(
        _("CIN / Passeport"),
        max_length=40,
        blank=True,
        help_text=_("CIN pour les clients marocains, passeport sinon."),
    )
    comment = models.TextField(_("commentaire"), blank=True)

    class Meta:
        verbose_name = _("client")
        verbose_name_plural = _("clients")
        ordering = ("name",)
        base_manager_name = "all_objects"
        indexes = [models.Index(fields=["country", "name"])]

    def __str__(self) -> str:
        return self.name

    @property
    def is_international(self) -> bool:
        """True when the client is not Moroccan."""
        return self.country.strip().lower() != MOROCCO.lower()

    @staticmethod
    def _digits(number: str) -> str:
        return "".join(ch for ch in (number or "") if ch.isdigit())

    @property
    def whatsapp_link(self) -> str:
        """``https://wa.me/<number>`` deep link (requirement 16), or ''."""
        digits = self._digits(self.whatsapp or self.telephone)
        if not digits:
            return ""
        # Local Moroccan numbers are stored as 06…/07…; wa.me needs the 212 prefix.
        if digits.startswith("0"):
            digits = f"212{digits[1:]}"
        return f"https://wa.me/{digits}"

    @property
    def tel_link(self) -> str:
        """``tel:`` link for click-to-call."""
        digits = self._digits(self.telephone)
        return f"tel:+{digits}" if digits else ""

    @property
    def booking_count(self) -> int:
        return self.bookings.count()
