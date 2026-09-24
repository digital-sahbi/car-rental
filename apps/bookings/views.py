"""Bookings views.

Route contract (from the spec):

* ``/bookings``               list — visible to every logged-in employee
* ``/bookings/add``           create
* ``/bookings/<id>``          detail == invoice view
* ``/bookings/<id>/edit``     admins/managers edit; employees file an EditRequest
"""
from __future__ import annotations

import csv
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, View

from apps.core.mixins import ADMIN, MANAGER, AuditContextMixin, ManagerRequiredMixin, RoleRequiredMixin
from apps.core.models import AuditAction
from apps.core.services import log_action
from apps.vehicles.models import Car

from . import services
from .forms import BookingFilterForm, BookingForm, BookingOptionFormSet, EditRequestForm
from .models import Booking, BookingStatus, EditRequest

EDITING_ROLES = (ADMIN, MANAGER)


class BookingListView(RoleRequiredMixin, ListView):
    """All bookings, with search / status / car filters and pagination."""

    model = Booking
    template_name = "bookings/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 25

    def get_queryset(self):
        self.sort = self.request.GET.get("sort", "").strip()
        # Managers may narrow to their own bookings; employees are always
        # scoped by the service, whatever the query string claims.
        self.only_own = self.request.GET.get("mine") == "1"
        return services.search_bookings(
            viewer=self.request.user,
            only_own=self.only_own,
            q=self.request.GET.get("q", "").strip(),
            status=self.request.GET.get("status", "").strip(),
            car_id=self.request.GET.get("car", "").strip(),
            client_id=self.request.GET.get("client", "").strip(),
            sort=self.sort,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = BookingFilterForm(self.request.GET or None)
        ctx["status_choices"] = BookingStatus.choices
        ctx["cars"] = Car.objects.all()
        ctx["total_count"] = self.get_queryset().count()
        ctx["sort"] = self.sort
        ctx["sort_choices"] = services.booking_sort_choices()
        ctx["can_see_all"] = services.can_see_all_bookings(self.request.user)
        ctx["only_own"] = self.only_own or not ctx["can_see_all"]
        return ctx


class BookingDetailView(RoleRequiredMixin, DetailView):
    """Booking detail — rendered as the invoice, with Print + PDF actions."""

    model = Booking
    template_name = "bookings/booking_detail.html"
    context_object_name = "booking"

    def get_object(self, queryset=None) -> Booking:
        """403 for a colleague's booking, 404 for a booking that doesn't exist."""
        return services.booking_for_viewer(pk=self.kwargs["pk"], viewer=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["invoice"] = getattr(self.object, "invoice", None)
        ctx["can_edit"] = self.request.user.role in EDITING_ROLES
        ctx["options"] = self.object.options.all()
        ctx["edit_requests"] = self.object.edit_requests.select_related("requested_by", "reviewed_by")
        return ctx


class BookingCreateView(RoleRequiredMixin, AuditContextMixin, CreateView):
    """Create a booking. Price is computed server-side."""

    model = Booking
    form_class = BookingForm
    template_name = "bookings/booking_form.html"

    def get_initial(self):
        initial = super().get_initial()
        car_id = self.request.GET.get("car")
        if car_id:
            car = Car.objects.filter(pk=car_id).first()
            if car:
                initial["car"] = car
                initial["pickup_location"] = _("Aéroport Marrakech-Menara")
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("option_formset", BookingOptionFormSet(self.request.POST or None))
        ctx["is_edit"] = False
        return ctx

    def form_valid(self, form):
        formset = BookingOptionFormSet(self.request.POST)
        if not formset.is_valid():
            return self.form_invalid(form)
        data = dict(form.cleaned_data)
        data.pop("total_price", None)
        options = [o for o in (formset.cleaned_data or []) if o and not o.get("DELETE")]
        try:
            self.object = services.create_booking(
                data=data,
                options=options,
                actor=self.get_actor(),
                request=self.request,
            )
        except ValidationError as exc:
            for field, errors in exc.message_dict.items():
                for error in errors:
                    form.add_error(field if field in form.fields else None, error)
            return self.form_invalid(form)

        messages.success(self.request, _("Réservation créée."))
        return redirect("bookings:booking_detail", pk=self.object.pk)


class BookingUpdateView(RoleRequiredMixin, AuditContextMixin, CreateView):
    """Direct edit — restricted to ADMIN / MANAGER."""

    model = Booking
    form_class = BookingForm
    template_name = "bookings/booking_form.html"
    allowed_roles = EDITING_ROLES

    def get_object(self) -> Booking:
        return services.booking_for_viewer(pk=self.kwargs["pk"], viewer=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        booking = self.get_object()
        ctx.setdefault("option_formset", BookingOptionFormSet(self.request.POST or None, instance=booking))
        ctx["booking"] = booking
        ctx["is_edit"] = True
        return ctx

    def form_valid(self, form):
        booking = self.get_object()
        formset = BookingOptionFormSet(self.request.POST, instance=booking)
        if not formset.is_valid():
            return self.form_invalid(form)
        data = dict(form.cleaned_data)
        data.pop("total_price", None)
        options = [o for o in (formset.cleaned_data or []) if o and not o.get("DELETE")]
        try:
            services.update_booking(
                booking=booking,
                data=data,
                options=options,
                actor=self.get_actor(),
                request=self.request,
            )
        except ValidationError as exc:
            for field, errors in exc.message_dict.items():
                for error in errors:
                    form.add_error(field if field in form.fields else None, error)
            return self.form_invalid(form)

        messages.success(self.request, _("Réservation enregistrée."))
        return redirect("bookings:booking_detail", pk=booking.pk)


class BookingEditDispatcherView(RoleRequiredMixin, View):
    """``/bookings/<id>/edit`` — branches on the caller's role.

    ADMIN/MANAGER are redirected to the direct edit form; everybody else gets
    the EditRequest form (their change must be approved).
    """

    def get(self, request, pk: int, *args, **kwargs):
        booking = services.booking_for_viewer(pk=pk, viewer=request.user)
        if request.user.role in EDITING_ROLES:
            return redirect("bookings:booking_update", pk=booking.pk)
        return render(
            request,
            "bookings/edit_request_form.html",
            {"booking": booking, "form": EditRequestForm()},
        )


class EditRequestCreateView(RoleRequiredMixin, AuditContextMixin, View):
    """Employee submits a change request."""

    def post(self, request, pk: int, *args, **kwargs):
        booking = services.booking_for_viewer(pk=pk, viewer=request.user)
        form = EditRequestForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Formulaire invalide."))
            return render(
                request,
                "bookings/edit_request_form.html",
                {"booking": booking, "form": form},
            )
        try:
            services.submit_edit_request(
                booking=booking,
                requested_by=self.get_actor(),
                reason=form.cleaned_data["reason"],
                proposed_changes=form.proposed_changes(),
                request=request,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
            return render(
                request,
                "bookings/edit_request_form.html",
                {"booking": booking, "form": form},
            )

        messages.success(request, _("Demande envoyée pour approbation."))
        return redirect("bookings:booking_detail", pk=booking.pk)


class EditRequestListView(ManagerRequiredMixin, ListView):
    """Manager queue of pending change requests."""

    model = EditRequest
    template_name = "bookings/edit_request_list.html"
    context_object_name = "edit_requests"
    paginate_by = 25

    def get_queryset(self):
        qs = EditRequest.objects.select_related("booking", "booking__car", "requested_by", "reviewed_by")
        status = self.request.GET.get("status", "").strip()
        if status in EditRequest.Status.values:
            qs = qs.filter(status=status)
        else:
            qs = qs.filter(status=EditRequest.Status.PENDING)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = EditRequest.Status.choices
        return ctx


class EditRequestReviewView(ManagerRequiredMixin, AuditContextMixin, View):
    """Approve or reject an edit request (POST only)."""

    def post(self, request, pk: int, *args, **kwargs):
        edit_request = get_object_or_404(EditRequest, pk=pk)
        approve = request.POST.get("decision") == "approve"
        comment = request.POST.get("comment", "")
        try:
            services.review_edit_request(
                edit_request=edit_request,
                approve=approve,
                reviewer=self.get_actor(),
                comment=comment,
                request=request,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(
                request,
                _("Demande approuvée.") if approve else _("Demande rejetée."),
            )
        return redirect("bookings:edit_request_list")


class BookingStatusUpdateView(RoleRequiredMixin, AuditContextMixin, View):
    """Change a booking's status (POST only)."""

    def post(self, request, pk: int, *args, **kwargs):
        booking = services.booking_for_viewer(pk=pk, viewer=request.user)
        try:
            services.change_status(
                booking=booking,
                status=request.POST.get("status", ""),
                actor=self.get_actor(),
                request=request,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, _("Statut mis à jour."))
        return redirect("bookings:booking_detail", pk=booking.pk)


class BookingDeleteView(RoleRequiredMixin, AuditContextMixin, DeleteView):
    """Soft-delete a booking."""

    model = Booking
    template_name = "bookings/booking_confirm_delete.html"
    success_url = reverse_lazy("bookings:booking_list")

    def get_object(self, queryset=None) -> Booking:
        return services.booking_for_viewer(pk=self.kwargs["pk"], viewer=self.request.user)

    def form_valid(self, form):
        services.delete_booking(
            booking=self.get_object(), actor=self.get_actor(), request=self.request
        )
        messages.success(self.request, _("Réservation archivée."))
        return HttpResponseRedirect(self.get_success_url())


class BookingExportView(RoleRequiredMixin, AuditContextMixin, View):
    """CSV / Excel export of the (filtered) booking list (requirement 19)."""

    COLUMNS = (
        ("id", _("N°")),
        ("client", _("Client")),
        ("car", _("Véhicule")),
        ("plate", _("Immatriculation")),
        ("start_date", _("Départ")),
        ("end_date", _("Retour")),
        ("days", _("Jours")),
        ("status", _("Statut")),
        ("pickup_location", _("Prise en charge")),
        ("return_location", _("Restitution")),
        ("total_price", _("Total")),
    )

    def get(self, request, *args, **kwargs):
        bookings = services.search_bookings(
            viewer=request.user,
            only_own=request.GET.get("mine") == "1",
            q=request.GET.get("q", "").strip(),
            status=request.GET.get("status", "").strip(),
            car_id=request.GET.get("car", "").strip(),
            sort=request.GET.get("sort", "").strip(),
        )
        fmt = request.GET.get("format", "csv").lower()

        if fmt == "xlsx":
            payload = self._rows(bookings)
            log_action(
                action=AuditAction.PRINT,
                model_name="Booking",
                object_repr=f"export xlsx ({len(payload)} lignes)",
                user=self.get_actor(),
                request=request,
            )
            return self._xlsx(payload)

        payload = self._rows(bookings)
        log_action(
            action=AuditAction.PRINT,
            model_name="Booking",
            object_repr=f"export csv ({len(payload)} lignes)",
            user=self.get_actor(),
            request=request,
        )
        return self._csv(payload)

    @staticmethod
    def _rows(bookings) -> list[list[str]]:
        rows: list[list[str]] = []
        for booking in bookings:
            rows.append(
                [
                    str(booking.pk),
                    booking.client.name,
                    booking.car.full_name,
                    booking.car.plate_number,
                    booking.start_date.strftime("%d/%m/%Y"),
                    booking.end_date.strftime("%d/%m/%Y"),
                    str(booking.days),
                    booking.get_status_display(),
                    booking.pickup_location,
                    booking.return_location,
                    str(booking.total_price),
                ]
            )
        return rows

    def _csv(self, rows: list[list[str]]) -> HttpResponse:
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="reservations-{date.today():%Y-%m-%d}.csv"'
        )
        response.write("\ufeff")  # BOM so Excel opens UTF-8 correctly
        writer = csv.writer(response, delimiter=";")
        writer.writerow([str(label) for _key, label in self.COLUMNS])
        writer.writerows(rows)
        return response

    def _xlsx(self, rows: list[list[str]]) -> HttpResponse:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Réservations"
        # ``str()`` is required: the labels are lazy translation proxies, which
        # openpyxl cannot coerce into a cell value on its own.
        sheet.append([str(label) for _key, label in self.COLUMNS])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(row)
        for column_cells in sheet.columns:
            width = max(len(str(cell.value or "")) for cell in column_cells) + 2
            sheet.column_dimensions[column_cells[0].column_letter].width = min(width, 40)

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="reservations-{date.today():%Y-%m-%d}.xlsx"'
        )
        workbook.save(response)
        return response
