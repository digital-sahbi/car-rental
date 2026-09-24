"""Clients forms."""
from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Client

# Short list of the nationalities this agency sees most; free text is allowed.
COMMON_COUNTRIES = [
    ("Maroc", _("Maroc")),
    ("France", _("France")),
    ("Espagne", _("Espagne")),
    ("Royaume-Uni", _("Royaume-Uni")),
    ("Allemagne", _("Allemagne")),
    ("États-Unis", _("États-Unis")),
    ("Belgique", _("Belgique")),
    ("Italie", _("Italie")),
    ("Pays-Bas", _("Pays-Bas")),
    ("Canada", _("Canada")),
]


class ClientForm(forms.ModelForm):
    """Create/update a client."""

    class Meta:
        model = Client
        fields = ("name", "telephone", "whatsapp", "email", "address", "country", "id_document", "comment")
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
            "country": forms.TextInput(attrs={"list": "country-list"}),
        }

    def clean_telephone(self) -> str:
        """Normalise spacing in phone numbers."""
        return (self.cleaned_data.get("telephone") or "").strip()

    def clean_name(self) -> str:
        """Title-case the client name for consistent listings."""
        return (self.cleaned_data.get("name") or "").strip()
