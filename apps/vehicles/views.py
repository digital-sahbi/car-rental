"""Vehicles views: fleet CRUD, status changes, maintenance."""
from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
    View,
)

from apps.core.mixins import AuditContextMixin, FormMessageMixin, RoleRequiredMixin

from . import services
from .forms import CarForm, CarImageFormSet, CarFilterForm, MaintenanceForm
from .models import Car, CarCategory, CarStatus, Maintenance


class CarListView(RoleRequiredMixin, ListView):
    """Fleet list with search, category/status filter and pagination."""

    model = Car
    template_name = "vehicles/car_list.html"
    context_object_name = "cars"
    paginate_by = 20

    def get_queryset(self):
        qs = services.cars_queryset()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(brand__icontains=q)
                | Q(model__icontains=q)
                | Q(name__icontains=q)
                | Q(plate_number__icontains=q)
            )
        category = self.request.GET.get("category", "").strip()
        if category:
            qs = qs.filter(category_id=category)
        status = self.request.GET.get("status", "").strip()
        if status in CarStatus.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = CarFilterForm(self.request.GET or None)
        ctx["categories"] = CarCategory.objects.all()
        ctx["status_choices"] = CarStatus.choices
        return ctx


class CarDetailView(RoleRequiredMixin, DetailView):
    """Car sheet: specs, gallery, booking history, maintenance history."""

    model = Car
    template_name = "vehicles/car_detail.html"
    context_object_name = "car"

    def get_queryset(self):
        return services.cars_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["images"] = self.object.images.all()
        ctx["maintenances"] = self.object.maintenances.select_related("created_by")[:10]
        ctx["bookings"] = (
            self.object.bookings.select_related("client")
            .order_by("-start_date")[:10]
        )
        return ctx


class CarCreateView(RoleRequiredMixin, AuditContextMixin, FormMessageMixin, CreateView):
    """Add a vehicle to the fleet (with gallery images)."""

    model = Car
    form_class = CarForm
    template_name = "vehicles/car_form.html"
    success_url = reverse_lazy("vehicles:car_list")
    success_message = _("Véhicule créé.")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("image_formset", CarImageFormSet(self.request.POST or None, self.request.FILES or None))
        return ctx

    def form_valid(self, form):
        formset = CarImageFormSet(self.request.POST, self.request.FILES)
        if not formset.is_valid():
            messages.error(self.request, _("Photos invalides."))
            return self.form_invalid(form)
        self.object = services.create_car(
            data=form.cleaned_data,
            actor=self.get_actor(),
            request=self.request,
        )
        formset.instance = self.object
        services.save_car_images(
            car=self.object, formset=formset, actor=self.get_actor(), request=self.request
        )
        messages.success(self.request, self.success_message)
        return HttpResponseRedirect(self.get_success_url())


class CarUpdateView(RoleRequiredMixin, AuditContextMixin, FormMessageMixin, UpdateView):
    """Edit a vehicle."""

    model = Car
    form_class = CarForm
    template_name = "vehicles/car_form.html"
    success_url = reverse_lazy("vehicles:car_list")
    success_message = _("Véhicule enregistré.")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault(
            "image_formset",
            CarImageFormSet(self.request.POST or None, self.request.FILES or None, instance=self.object),
        )
        return ctx

    def form_valid(self, form):
        formset = CarImageFormSet(self.request.POST, self.request.FILES, instance=self.object)
        if not formset.is_valid():
            messages.error(self.request, _("Photos invalides."))
            return self.form_invalid(form)
        services.update_car(
            car=self.object,
            data=form.cleaned_data,
            actor=self.get_actor(),
            request=self.request,
        )
        services.save_car_images(
            car=self.object, formset=formset, actor=self.get_actor(), request=self.request
        )
        messages.success(self.request, self.success_message)
        return HttpResponseRedirect(self.get_success_url())


class CarDeleteView(RoleRequiredMixin, AuditContextMixin, DeleteView):
    """Soft-delete a vehicle."""

    model = Car
    template_name = "vehicles/car_confirm_delete.html"
    success_url = reverse_lazy("vehicles:car_list")

    def form_valid(self, form):
        services.delete_car(car=self.get_object(), actor=self.get_actor(), request=self.request)
        messages.success(self.request, _("Véhicule archivé."))
        return HttpResponseRedirect(self.get_success_url())


class CarStatusUpdateView(RoleRequiredMixin, AuditContextMixin, View):
    """Change a car's status (POST only)."""

    def post(self, request, pk: int, *args, **kwargs):
        car = Car.objects.filter(pk=pk).first()
        if car is None:
            messages.error(request, _("Véhicule introuvable."))
            return HttpResponseRedirect(reverse("vehicles:car_list"))
        status = request.POST.get("status", "")
        if status not in CarStatus.values:
            messages.error(request, _("État invalide."))
        else:
            services.sync_status(car=car, status=status, actor=self.get_actor(), request=request)
            messages.success(request, _("État mis à jour."))
        return HttpResponseRedirect(reverse("vehicles:car_detail", args=[pk]))


class MaintenanceListView(RoleRequiredMixin, ListView):
    """Maintenance history across the fleet."""

    model = Maintenance
    template_name = "vehicles/maintenance_list.html"
    context_object_name = "maintenances"
    paginate_by = 25

    def get_queryset(self):
        qs = Maintenance.objects.select_related("car", "created_by")
        car_id = self.request.GET.get("car", "").strip()
        if car_id:
            qs = qs.filter(car_id=car_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cars"] = Car.objects.all()
        ctx["car_filter"] = self.request.GET.get("car", "")
        return ctx


class MaintenanceCreateView(RoleRequiredMixin, AuditContextMixin, FormMessageMixin, CreateView):
    """Log a maintenance intervention."""

    model = Maintenance
    form_class = MaintenanceForm
    template_name = "vehicles/maintenance_form.html"
    success_url = reverse_lazy("vehicles:maintenance_list")
    success_message = _("Maintenance enregistrée.")

    def form_valid(self, form):
        data = dict(form.cleaned_data)
        car = data.pop("car")
        # Assign to ``self.object`` before redirecting. Django 6.1's
        # ``ModelFormMixin.get_success_url`` evaluates
        # ``self.success_url.format(**self.object.__dict__)``, so leaving
        # ``self.object`` as None raises
        # ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
        self.object = services.create_maintenance(
            car=car,
            data=data,
            actor=self.get_actor(),
            request=self.request,
        )
        messages.success(self.request, self.success_message)
        return HttpResponseRedirect(self.get_success_url())
