"""Invoicing views: issue, printable HTML, PDF download.

The HTML print view is the "Print (HTML)" button on the booking detail page;
``window.print()`` is triggered from the template.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View

from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.core.mixins import AuditContextMixin, RoleRequiredMixin
from apps.core.models import Promotion

from . import services
from .models import Invoice


class InvoiceListView(RoleRequiredMixin, ListView):
    """Issued invoices, newest first, with search + pagination."""

    model = Invoice
    template_name = "invoicing/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25

    def get_queryset(self):
        # Same visibility rule as the bookings list.
        qs = services.invoices_queryset().filter(
            booking__in=booking_services.bookings_visible_to(self.request.user)
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            from django.db.models import Q

            qs = qs.filter(
                Q(number__icontains=q)
                | Q(booking__client__name__icontains=q)
                | Q(booking__car__plate_number__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class InvoiceIssueView(RoleRequiredMixin, AuditContextMixin, View):
    """Issue the invoice for a booking (POST only)."""

    def post(self, request, pk: int, *args, **kwargs):
        booking = booking_services.booking_for_viewer(pk=pk, viewer=request.user)
        promotion = None
        code = (request.POST.get("promotion_code") or "").strip().upper()
        if code:
            promotion = Promotion.objects.filter(code=code).first()
            if promotion is None:
                messages.error(request, _("Code promotion inconnu."))
                return redirect("bookings:booking_detail", pk=pk)

        try:
            invoice = services.issue_invoice(
                booking=booking,
                actor=self.get_actor(),
                promotion=promotion,
                request=request,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, _("Facture %(number)s émise.") % {"number": invoice.number})
        return redirect("bookings:booking_detail", pk=pk)


class InvoicePrintView(RoleRequiredMixin, AuditContextMixin, View):
    """Printable HTML invoice (``window.print()``)."""

    def get(self, request, pk: int, *args, **kwargs):
        # Same visibility rule as the booking detail page: an employee must not
        # be able to print a colleague's invoice by guessing the booking id.
        booking_services.booking_for_viewer(pk=pk, viewer=request.user)
        invoice = get_object_or_404(services.invoices_queryset(), booking_id=pk)
        services.record_print(invoice=invoice, actor=self.get_actor(), request=request)
        from .pdf import invoice_html

        return HttpResponse(invoice_html(invoice=invoice))


class InvoicePDFView(RoleRequiredMixin, AuditContextMixin, View):
    """Download the invoice as a PDF."""

    def get(self, request, pk: int, *args, **kwargs):
        # Same visibility rule as the booking detail page: see InvoicePrintView.
        booking_services.booking_for_viewer(pk=pk, viewer=request.user)
        invoice = get_object_or_404(services.invoices_queryset(), booking_id=pk)
        try:
            payload = services.render_pdf(invoice=invoice)
        except RuntimeError as exc:
            messages.error(request, str(exc))
            return redirect("bookings:booking_detail", pk=pk)

        services.record_print(invoice=invoice, actor=self.get_actor(), request=request)
        response = HttpResponse(payload, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{invoice.number}.pdf"'
        return response
