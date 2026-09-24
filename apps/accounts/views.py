"""Accounts views: auth (login/logout) + admin-only employee CRUD."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View
from django.shortcuts import get_object_or_404, redirect

from apps.core.mixins import RoleRequiredMixin

from .forms import EmailAuthenticationForm, EmployeeForm
from .models import Role, User
from . import services


class CrmLoginView(LoginView):
    """Email login; records a LOGIN audit entry on success."""

    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        services.log_login(user=self.request.user, request=self.request)
        return response


class CrmLogoutView(View):
    """Records a LOGOUT audit entry then logs the user out."""

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            services.log_logout(user=request.user, request=request)
        from django.contrib.auth import logout

        logout(request)
        return redirect("accounts:login")


class EmployeeListView(RoleRequiredMixin, ListView):
    """Admin-only: list all employees with search + pagination."""

    allowed_roles = (Role.ADMIN,)
    model = User
    template_name = "accounts/employee_list.html"
    context_object_name = "employees"
    paginate_by = 20

    def get_queryset(self):
        qs = services.employees_queryset()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(cin__icontains=q)
            )
        role = self.request.GET.get("role", "").strip()
        if role in Role.values:
            qs = qs.filter(role=role)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["role_filter"] = self.request.GET.get("role", "")
        ctx["role_choices"] = services.role_choices()
        return ctx


class EmployeeCreateView(RoleRequiredMixin, CreateView):
    """Admin-only: create an employee."""

    allowed_roles = (Role.ADMIN,)
    model = User
    form_class = EmployeeForm
    template_name = "accounts/employee_form.html"
    success_url = reverse_lazy("accounts:employee_list")

    def form_valid(self, form):
        self.object = services.create_employee(
            data=form.cleaned_data.copy(),
            actor=self.request.user,
            request=self.request,
        )
        return redirect(self.get_success_url())


class EmployeeUpdateView(RoleRequiredMixin, UpdateView):
    """Admin-only: edit an employee (password optional)."""

    allowed_roles = (Role.ADMIN,)
    model = User
    form_class = EmployeeForm
    template_name = "accounts/employee_form.html"
    success_url = reverse_lazy("accounts:employee_list")

    def form_valid(self, form):
        services.update_employee(
            user=self.object,
            data=form.cleaned_data.copy(),
            actor=self.request.user,
            request=self.request,
        )
        return redirect(self.get_success_url())


class EmployeeToggleActiveView(RoleRequiredMixin, View):
    """Admin-only: deactivate / reactivate an employee (POST only)."""

    allowed_roles = (Role.ADMIN,)

    def post(self, request, pk: int, *args, **kwargs):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
            return redirect("accounts:employee_list")
        if user.is_active:
            services.deactivate_employee(user=user, actor=request.user, request=request)
        else:
            services.reactivate_employee(user=user, actor=request.user, request=request)
        return redirect("accounts:employee_list")