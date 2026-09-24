"""modeltranslation registrations for the core app."""
from __future__ import annotations

from modeltranslation.translator import TranslationOptions, register

from .models import CompanySettings, Promotion


@register(Promotion)
class PromotionTranslationOptions(TranslationOptions):
    fields = ("description",)


@register(CompanySettings)
class CompanySettingsTranslationOptions(TranslationOptions):
    fields = ("invoice_footer",)
