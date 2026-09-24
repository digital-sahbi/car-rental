"""modeltranslation registrations for vehicles."""
from __future__ import annotations

from modeltranslation.translator import TranslationOptions, register

from .models import Car, CarCategory


@register(CarCategory)
class CarCategoryTranslationOptions(TranslationOptions):
    fields = ("description",)


@register(Car)
class CarTranslationOptions(TranslationOptions):
    fields = ("description",)
