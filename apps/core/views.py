"""Core views: dashboard, company settings, promotions, audit log."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, TemplateView, UpdateView, View

from .forms import CompanySettingsForm, PromotionForm
from .mixins import AdminRequiredMixin, AuditContextMixin, FormMessageMixin, RoleRequiredMixin
from .models import AuditAction, AuditLog, CompanySettings, Promotion
from . import notifications as notifications_service
from . import services


class DashboardView(RoleRequiredMixin, TemplateView):
    """Landing page: availability, today's activity and fleet stats.

    ``RoleRequiredMixin`` with an empty ``allowed_roles`` means "any logged-in
    employee" — requirement 2, no anonymous access.
    """

    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        # Imported lazily so that core stays importable on its own.
        from apps.bookings import services as booking_services
        from apps.bookings.models import Booking, BookingStatus, EditRequest
        from apps.invoicing.models import Invoice
        from apps.vehicles.models import Car, CarStatus

        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        month_start = today.replace(day=1)

        # Booking figures follow the same visibility rule as the booking list:
        # an employee only ever sees their own activity, so the dashboard
        # cannot be used to read a colleague's bookings.
        mine = booking_services.bookings_visible_to(self.request.user)
        ctx["scoped_to_me"] = not booking_services.can_see_all_bookings(self.request.user)
        ctx["today"] = today
        ctx["today_bookings"] = (
            mine.filter(start_date=today)
            .select_related("car", "client", "user")
            .order_by("start_date")
        )
        ctx["pickups_today"] = ctx["today_bookings"].count()
        ctx["returns_today"] = mine.filter(end_date=today).count()

        ctx["cars_out"] = Car.objects.filter(status=CarStatus.RENTED).count()
        ctx["available_cars_count"] = Car.objects.filter(status=CarStatus.AVAILABLE).count()
        ctx["cars_in_maintenance"] = Car.objects.filter(status=CarStatus.MAINTENANCE).count()

        ctx["revenue_month"] = (
            Invoice.objects.filter(issued_at__date__gte=month_start).aggregate(
                total=Sum("total_amount")
            )["total"]
            or Decimal("0.00")
        )

        ctx["pending_edit_requests"] = EditRequest.objects.filter(
            status=EditRequest.Status.PENDING,
            booking__in=mine,
        ).count()

        ctx["fleet_by_status"] = (
            Car.objects.values("status").annotate(total=Count("id")).order_by("status")
        )
        ctx["fleet_by_category"] = (
            Car.objects.values("category__name")
            .annotate(total=Count("id"))
            .order_by("-total")
        )
        ctx["fleet_total"] = Car.objects.count()
        ctx["recent_bookings"] = (
            mine.select_related("car", "client")
            .order_by("-created_at")[:8]
        )
        return ctx


class MarkNotificationsSeenView(RoleRequiredMixin, View):
    """POST: remember that the bell panel has been opened, clearing the badge."""

    def post(self, request, *args, **kwargs):
        notifications_service.mark_notifications_seen(request.user)
        return JsonResponse({"unread": 0})


class ActivityHistoryView(RoleRequiredMixin, ListView):
    """Action history: what happened to the bookings this user may see.

    Administrators get the whole journal here too; everyone else gets a feed
    scoped by the same visibility rule as the bookings list.
    """

    template_name = "core/activity.html"
    context_object_name = "entries"
    paginate_by = 40

    def get_queryset(self):
        queryset = notifications_service.activity_queryset_for(self.request.user)
        action = self.request.GET.get("action", "").strip()
        if action in AuditAction.values:
            queryset = queryset.filter(action=action)
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action_choices"] = AuditAction.choices
        ctx["action_filter"] = self.request.GET.get("action", "")
        ctx["history_url"] = notifications_service.history_url_for(self.request.user)
        return ctx


class CompanySettingsUpdateView(
    AdminRequiredMixin, AuditContextMixin, FormMessageMixin, UpdateView
):
    """Admin-only: edit the company singleton."""

    model = CompanySettings
    form_class = CompanySettingsForm
    template_name = "core/company_settings.html"
    success_url = reverse_lazy("core:settings")
    success_message = _("Paramètres de l'entreprise enregistrés.")

    def get_object(self, queryset=None) -> CompanySettings:
        return CompanySettings.load()

    def form_valid(self, form):
        before = services.snapshot(self.get_object())
        response = super().form_valid(form)
        services.log_action(
            action="UPDATE",
            instance=self.object,
            changes=services.business_diff(before, services.snapshot(self.object)),
            **self.audit_kwargs(),
        )
        return response


class PromotionListView(AdminRequiredMixin, ListView):
    """Admin-only: list promotions with search + pagination."""

    model = Promotion
    template_name = "core/promotion_list.html"
    context_object_name = "promotions"
    paginate_by = 20

    def get_queryset(self):
        qs = Promotion.objects.select_related("created_by")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(description__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class PromotionCreateView(
    AdminRequiredMixin, AuditContextMixin, FormMessageMixin, CreateView
):
    """Admin-only: create a promotion."""

    model = Promotion
    form_class = PromotionForm
    template_name = "core/promotion_form.html"
    success_url = reverse_lazy("core:promotion_list")
    success_message = _("Promotion créée.")

    def form_valid(self, form):
        form.instance.created_by = self.get_actor()
        response = super().form_valid(form)
        services.log_action(
            action="CREATE",
            instance=self.object,
            changes={"created": {"code": self.object.code}},
            **self.audit_kwargs(),
        )
        return response


class PromotionUpdateView(
    AdminRequiredMixin, AuditContextMixin, FormMessageMixin, UpdateView
):
    """Admin-only: edit a promotion."""

    model = Promotion
    form_class = PromotionForm
    template_name = "core/promotion_form.html"
    success_url = reverse_lazy("core:promotion_list")
    success_message = _("Promotion enregistrée.")

    def form_valid(self, form):
        before = services.snapshot(self.get_object())
        response = super().form_valid(form)
        services.log_action(
            action="UPDATE",
            instance=self.object,
            changes=services.business_diff(before, services.snapshot(self.object)),
            **self.audit_kwargs(),
        )
        return response


class AuditLogListView(AdminRequiredMixin, ListView):
    """Admin-only: browse the audit journal with filters + pagination."""

    model = AuditLog
    template_name = "core/audit_log_list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user")
        action = self.request.GET.get("action", "").strip()
        if action:
            qs = qs.filter(action=action)
        model_name = self.request.GET.get("model", "").strip()
        if model_name:
            qs = qs.filter(model_name__iexact=model_name)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(object_repr__icontains=q)
                | Q(user__email__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["action_filter"] = self.request.GET.get("action", "")
        ctx["model_filter"] = self.request.GET.get("model", "")
        ctx["action_choices"] = AuditAction.choices
        ctx["model_choices"] = (
            AuditLog.objects.values_list("model_name", flat=True).distinct().order_by("model_name")
        )
        return ctx
