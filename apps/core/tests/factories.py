"""Shared object builders for the test suite.

Deliberately plain functions rather than a factory library: the suite should
exercise the real models and services with real (if minimal) rows.
"""
from __future__ import annotations

import itertools
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clients.models import Client
from apps.vehicles.models import Car, CarCategory, CarStatus, FuelType, Transmission

DEFAULT_PASSWORD = "TestPass123!"

# Monotonic counters so repeated factory calls inside one test never collide on
# a unique column (``User.email``, ``Car.plate_number``).
_user_seq = itertools.count(1)
_car_seq = itertools.count(1)


def make_user(
    *,
    email: str | None = None,
    role: str = Role.EMPLOYEE,
    first_name: str = "Test",
    last_name: str = "User",
    password: str = DEFAULT_PASSWORD,
    **extra,
) -> User:
    """Create an employee with a usable password and a unique email."""
    if email is None:
        email = f"user{next(_user_seq)}@smartrent.ma"
    user = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=role,
        is_staff=role in (Role.ADMIN, Role.MANAGER),
        **extra,
    )
    user.set_password(password)
    user.save()
    return user


def make_admin(**kwargs) -> User:
    kwargs.setdefault("role", Role.ADMIN)
    kwargs.setdefault("is_superuser", True)
    return make_user(**kwargs)


def make_manager(**kwargs) -> User:
    kwargs.setdefault("role", Role.MANAGER)
    return make_user(**kwargs)


def make_employee(**kwargs) -> User:
    kwargs.setdefault("role", Role.EMPLOYEE)
    return make_user(**kwargs)


def make_category(name: str = CarCategory.Name.ECONOMY) -> CarCategory:
    category, _ = CarCategory.objects.get_or_create(name=name)
    return category


def make_car(
    *,
    plate_number: str | None = None,
    price_per_day: str | Decimal = "300.00",
    status: str = CarStatus.AVAILABLE,
    category: CarCategory | None = None,
    **extra,
) -> Car:
    """Create a car with sensible defaults and a unique plate number."""
    today = timezone.localdate()
    if plate_number is None:
        plate_number = f"TEST-{next(_car_seq):04d}"
    return Car.objects.create(
        name=extra.pop("name", "Clio"),
        brand=extra.pop("brand", "Renault"),
        model=extra.pop("model", "Clio 5"),
        plate_number=plate_number,
        category=category or make_category(),
        price_per_day=Decimal(str(price_per_day)),
        status=status,
        fuel_type=extra.pop("fuel_type", FuelType.DIESEL),
        transmission=extra.pop("transmission", Transmission.MANUAL),
        seats=extra.pop("seats", 5),
        year=extra.pop("year", today.year - 1),
        mileage=extra.pop("mileage", 10_000),
        **extra,
    )


def make_client(
    *,
    name: str = "Ahmed El Fassi",
    telephone: str = "+212 661 111 111",
    country: str = "Maroc",
    **extra,
) -> Client:
    """Create a client."""
    return Client.objects.create(
        name=name,
        telephone=telephone,
        country=country,
        **extra,
    )


def date_range(*, start_offset: int, duration: int):
    """Absolute (start, end) dates relative to today, inclusive of both."""
    today = timezone.localdate()
    start = today + timedelta(days=start_offset)
    return start, start + timedelta(days=duration)
