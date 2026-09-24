"""Core forms: company settings and promotions."""
from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import CompanySettings, Promotion


class CompanySettingsForm(forms.ModelForm):
    """Edit the company singleton used on every invoice."""

    class Meta:
        model = CompanySettings
        fields = (
            "company_name",
            "logo",
            "address",
            "phone",
            "email",
            "website",
            "ice",
            "rc",
            "patente",
            "if_number",
            "bank_details",
            "default_vat",
            "invoice_footer",
            "default_language",
        )
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "bank_details": forms.Textarea(attrs={"rows": 3}),
            "invoice_footer": forms.Textarea(attrs={"rows": 3}),
        }


class PromotionForm(forms.ModelForm):
    """Create/update a promotion."""

    class Meta:
        model = Promotion
        fields = (
            "code",
            "description",
            "discount_type",
            "discount_value",
            "valid_from",
            "valid_to",
            "is_active",
        )
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "valid_to": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs.update({"placeholder": "PROMO-2026"})

    def clean_code(self) -> str:
        """Normalise the code to upper case."""
        return (self.cleaned_data.get("code") or "").strip().upper()
