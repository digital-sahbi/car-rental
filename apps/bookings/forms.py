"""Bookings forms — no view ever reads ``request.POST`` directly (requirement 8)."""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.clients.models import Client
from apps.vehicles.models import Car, CarStatus

from .models import Booking, BookingOption, BookingStatus, EditRequest, FuelPolicy, MileagePolicy

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class BookingForm(forms.ModelForm):
    """Create/update a booking.

    ``total_price`` is intentionally absent: it is computed by
    :mod:`apps.bookings.services` from ``car.price_per_day`` and the date range.
    """

    class Meta:
        model = Booking
        fields = (
            "car",
            "client",
            "start_date",
            "end_date",
            "status",
            "pickup_location",
            "return_location",
            "fuel_policy",
            "mileage_policy",
            "mileage_limit",
            "notes",
        )
        widgets = {
            "start_date": DATE_WIDGET,
            "end_date": DATE_WIDGET,
            "notes": forms.Textarea(attrs={"rows": 3}),
            "pickup_location": forms.TextInput(
                attrs={"placeholder": _("Aéroport Marrakech, Centre-ville, Hôtel…")}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only genuinely bookable cars can be chosen (a car in maintenance is
        # still selectable when editing, otherwise the form would be invalid).
        bookable = Car.objects.exclude(status=CarStatus.OUT_OF_SERVICE)
        if self.instance.pk:
            bookable = Car.objects.filter(
                models_q_self_or_available(self.instance.car_id)
            )
        self.fields["car"].queryset = bookable.select_related("category")
        self.fields["client"].queryset = Client.objects.all()
        self.fields["car"].empty_label = _("— Choisir un véhicule —")
        self.fields["client"].empty_label = _("— Choisir un client —")
        self.fields["pickup_location"].initial = self.fields["pickup_location"].initial or _(
            "Aéroport Marrakech-Menara"
        )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end <= start:
            self.add_error("end_date", _("La date de retour doit être postérieure au départ."))
        if cleaned.get("mileage_policy") == MileagePolicy.LIMITED and not cleaned.get("mileage_limit"):
            self.add_error("mileage_limit", _("Indiquez la limite de kilométrage."))
        return cleaned


def models_q_self_or_available(car_id):
    """Helper: keep the current car selectable while editing."""
    from django.db.models import Q

    return Q(status=CarStatus.AVAILABLE) | Q(status=CarStatus.RENTED) | Q(pk=car_id)


class BookingOptionForm(forms.ModelForm):
    """A single extra."""

    class Meta:
        model = BookingOption
        fields = ("option_type", "price", "quantity")


BookingOptionFormSet = inlineformset_factory(
    Booking,
    BookingOption,
    form=BookingOptionForm,
    extra=3,
    can_delete=True,
)


class BookingFilterForm(forms.Form):
    """Search / filter widget for the booking list (requirement 13)."""

    q = forms.CharField(
        required=False,
        label=_("Recherche"),
        widget=forms.TextInput(
            attrs={"placeholder": _("Client, immatriculation, lieu…"), "class": "form-control"}
        ),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", _("Tous les statuts"))] + list(BookingStatus.choices),
        label=_("Statut"),
    )
    car = forms.ModelChoiceField(queryset=Car.objects.all(), required=False, label=_("Véhicule"))


class EditRequestForm(forms.ModelForm):
    """Employee-submitted change request."""

    class Meta:
        model = EditRequest
        fields = ("reason",)
        widgets = {"reason": forms.Textarea(attrs={"rows": 4})}

    #: The fields an employee is allowed to propose changes to.
    EDITABLE_FIELDS = (
        "start_date",
        "end_date",
        "car",
        "pickup_location",
        "return_location",
        "fuel_policy",
        "mileage_policy",
        "mileage_limit",
        "notes",
    )

    start_date = forms.DateField(required=False, widget=DATE_WIDGET, label=_("Nouvelle date de départ"))
    end_date = forms.DateField(required=False, widget=DATE_WIDGET, label=_("Nouvelle date de retour"))
    car = forms.ModelChoiceField(queryset=Car.objects.all(), required=False, label=_("Nouveau véhicule"))
    pickup_location = forms.CharField(required=False, label=_("Lieu de prise en charge"))
    return_location = forms.CharField(required=False, label=_("Lieu de restitution"))
    fuel_policy = forms.ChoiceField(
        required=False, choices=[("", "—")] + list(FuelPolicy.choices), label=_("Carburant")
    )
    mileage_policy = forms.ChoiceField(
        required=False, choices=[("", "—")] + list(MileagePolicy.choices), label=_("Kilométrage")
    )
    mileage_limit = forms.IntegerField(required=False, min_value=0, label=_("Limite (km)"))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("Notes"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("start_date", "end_date", "car", "pickup_location", "return_location",
                     "fuel_policy", "mileage_policy", "mileage_limit", "notes"):
            self.fields[name].required = False

    def proposed_changes(self) -> dict:
        """Only the fields the user actually filled in, as ``{field: value}``."""
        changes: dict = {}
        for name in self.EDITABLE_FIELDS:
            value = self.cleaned_data.get(name)
            if value not in (None, "", []):
                changes[name] = value.pk if hasattr(value, "pk") else value
        return changes
