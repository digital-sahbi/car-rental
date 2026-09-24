"""Vehicles forms."""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import Car, CarImage, CarCategory, CarStatus, Maintenance


class CarForm(forms.ModelForm):
    """Create/update a car."""

    class Meta:
        model = Car
        fields = (
            "name",
            "brand",
            "model",
            "plate_number",
            "category",
            "price_per_day",
            "picture",
            "status",
            "fuel_type",
            "transmission",
            "seats",
            "year",
            "mileage",
            "description",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["picture"].help_text = _(
            "Devient l'image principale du véhicule. Si une photo de la galerie "
            "était marquée « principale », elle ne le sera plus."
        )

    def clean_plate_number(self) -> str:
        """Normalise the plate (upper case, no stray spaces)."""
        return " ".join((self.cleaned_data.get("plate_number") or "").split()).upper()


class CarImageForm(forms.ModelForm):
    """One gallery image."""

    class Meta:
        model = CarImage
        fields = ("image", "is_main")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_main"].help_text = _(
            "Coche pour faire de cette photo la photo principale "
            "(remplace la photo principale du véhicule)."
        )

    def validate_unique(self) -> None:
        """Skip the "one main image per car" check.

        A form is validated against the *current* database state, so promoting
        a photo would always clash with the outgoing main before it could be
        demoted. ``services.save_car_images()`` demotes the other rows first
        and so restores the invariant this check would otherwise enforce.
        """
        return


CarImageFormSet = inlineformset_factory(
    Car,
    CarImage,
    form=CarImageForm,
    extra=3,
    can_delete=True,
)


class MaintenanceForm(forms.ModelForm):
    """Record a maintenance intervention."""

    class Meta:
        model = Maintenance
        fields = ("car", "date", "description", "cost", "mileage_at_service", "next_service_date")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "next_service_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class CarFilterForm(forms.Form):
    """Filter/search widget for the fleet list (requirement 13)."""

    q = forms.CharField(
        required=False,
        label=_("Recherche"),
        widget=forms.TextInput(
            attrs={"placeholder": _("Marque, modèle, immatriculation…"), "class": "form-control"}
        ),
    )
    category = forms.ModelChoiceField(
        queryset=CarCategory.objects.all(), required=False, label=_("Catégorie")
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", _("Tous les états"))] + list(CarStatus.choices),
        label=_("État"),
    )
