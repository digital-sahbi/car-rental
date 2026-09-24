"""Clients views: CRUD with search + pagination."""
from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.core.mixins import AuditContextMixin, FormMessageMixin, RoleRequiredMixin

from . import services
from .forms import ClientForm
from .models import Client


class ClientListView(RoleRequiredMixin, ListView):
    """Client book with search + pagination."""

    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 20

    def get_queryset(self):
        return services.search_clients(self.request.GET.get("q", ""))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class ClientDetailView(RoleRequiredMixin, DetailView):
    """Client sheet: contact details + booking history."""

    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["bookings"] = (
            self.object.bookings.select_related("car")
            .order_by("-start_date")
        )
        return ctx


class ClientCreateView(RoleRequiredMixin, AuditContextMixin, FormMessageMixin, CreateView):
    """Add a client."""

    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"
    success_url = reverse_lazy("clients:client_list")
    success_message = _("Client créé.")

    def form_valid(self, form):
        self.object = services.create_client(
            data=form.cleaned_data,
            actor=self.get_actor(),
            request=self.request,
        )
        messages.success(self.request, self.success_message)
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url:
            return HttpResponseRedirect(next_url)
        return HttpResponseRedirect(self.get_success_url())


class ClientUpdateView(RoleRequiredMixin, AuditContextMixin, FormMessageMixin, UpdateView):
    """Edit a client."""

    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"
    success_url = reverse_lazy("clients:client_list")
    success_message = _("Client enregistré.")

    def form_valid(self, form):
        services.update_client(
            client=self.object,
            data=form.cleaned_data,
            actor=self.get_actor(),
            request=self.request,
        )
        messages.success(self.request, self.success_message)
        return HttpResponseRedirect(self.get_success_url())


class ClientDeleteView(RoleRequiredMixin, AuditContextMixin, DeleteView):
    """Soft-delete a client."""

    model = Client
    template_name = "clients/client_confirm_delete.html"
    success_url = reverse_lazy("clients:client_list")

    def form_valid(self, form):
        services.delete_client(client=self.get_object(), actor=self.get_actor(), request=self.request)
        messages.success(self.request, _("Client archivé."))
        return HttpResponseRedirect(self.get_success_url())
