"""Seed the CRM with realistic demo data.

Usage::

    python manage.py seed_demo_data
    python manage.py seed_demo_data --fresh     # wipe CRM data first

Creates: 3 users (admin / manager / employee), 5 car categories, 15 cars with
generated placeholder images, 10 clients (Moroccan + international),
20 bookings across all statuses, invoices for the completed ones, 2 promotions
and the company-settings singleton.

The command is **idempotent**: users are matched by email and reference data is
created only when missing, so re-running it will not duplicate rows.
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Role, User
from apps.bookings.models import Booking, BookingOption, BookingStatus
from apps.bookings import services as booking_services
from apps.clients.models import Client
from apps.core.models import CompanySettings, DiscountType, Promotion
from apps.invoicing.models import Invoice
from apps.invoicing import services as invoice_services
from apps.vehicles.models import Car, CarCategory, CarImage, CarStatus, FuelType, Transmission

DEFAULT_PASSWORD = "SmartRent2026!"

USERS = [
    {
        "email": "admin@smartrent.ma",
        "first_name": "Youssef",
        "last_name": "El Amrani",
        "role": Role.ADMIN,
        "telephone": "+212 661 000 001",
        "cin": "AA111111",
        "is_staff": True,
        "is_superuser": True,
    },
    {
        "email": "manager@smartrent.ma",
        "first_name": "Salma",
        "last_name": "Bennani",
        "role": Role.MANAGER,
        "telephone": "+212 661 000 002",
        "cin": "BB222222",
        "is_staff": True,
        "is_superuser": False,
    },
    {
        "email": "employe@smartrent.ma",
        "first_name": "Karim",
        "last_name": "Ouazzani",
        "role": Role.EMPLOYEE,
        "telephone": "+212 661 000 003",
        "cin": "CC333333",
        "is_staff": False,
        "is_superuser": False,
    },
]

# Category copy per language, keyed by the modeltranslation field suffix.
CATEGORIES = [
    (
        CarCategory.Name.ECONOMY,
        {
            "fr": "Petites citadines économiques, idéales pour la ville.",
            "en": "Small, economical city cars, ideal for driving in town.",
            "ar": "سيارات صغيرة اقتصادية، مثالية للتنقل داخل المدينة.",
        },
    ),
    (
        CarCategory.Name.COMPACT,
        {
            "fr": "Compactes confortables pour deux personnes et bagages.",
            "en": "Comfortable compacts for two people and their luggage.",
            "ar": "سيارات مدمجة مريحة لشخصين مع الأمتعة.",
        },
    ),
    (
        CarCategory.Name.FAMILY,
        {
            "fr": "Berlines familiales spacieuses, jusqu'à 5 passagers.",
            "en": "Spacious family saloons, seating up to 5 passengers.",
            "ar": "سيارات عائلية فسيحة تتسع حتى 5 ركاب.",
        },
    ),
    (
        CarCategory.Name.SUV,
        {
            "fr": "SUV et 4x4 pour l'Atlas, le désert et les pistes.",
            "en": "SUVs and 4x4s for the Atlas mountains, the desert and rough tracks.",
            "ar": "سيارات SUV ورباعية الدفع لجبال الأطلس والصحراء والمسالك الوعرة.",
        },
    ),
    (
        CarCategory.Name.LUXURY,
        {
            "fr": "Berlines et SUV de prestige avec équipement premium.",
            "en": "Prestige saloons and SUVs with premium equipment.",
            "ar": "سيارات فاخرة من الفئة العليا بتجهيزات راقية.",
        },
    ),
]

CARS = [
    # (name, brand, model, plate, category, price/day, fuel, gearbox, seats, year, km)
    ("Clio", "Renault", "Clio 5", "12345-A-1", "economy", 250, "diesel", "manual", 5, 2023, 45000),
    ("Picanto", "Kia", "Picanto", "12346-A-2", "economy", 220, "petrol", "manual", 5, 2022, 61000),
    ("Sandero", "Dacia", "Sandero Stepway", "12347-A-3", "economy", 240, "diesel", "manual", 5, 2023, 38000),
    ("208", "Peugeot", "208", "12348-B-1", "compact", 320, "diesel", "automatic", 5, 2024, 21000),
    ("Clio RS", "Renault", "Clio RS Line", "12349-B-2", "compact", 350, "petrol", "automatic", 5, 2024, 18000),
    ("Golf 8", "Volkswagen", "Golf 8", "12350-B-3", "compact", 420, "diesel", "automatic", 5, 2023, 33000),
    ("Octavia", "Skoda", "Octavia Combi", "12351-C-1", "family", 450, "diesel", "automatic", 5, 2023, 52000),
    ("Passat", "Volkswagen", "Passat Variant", "12352-C-2", "family", 550, "diesel", "automatic", 5, 2022, 74000),
    ("Duster", "Dacia", "Duster 4x4", "12353-D-1", "suv", 480, "diesel", "manual", 5, 2024, 29000),
    ("Tucson", "Hyundai", "Tucson", "12354-D-2", "suv", 620, "diesel", "automatic", 5, 2024, 24000),
    ("Prado", "Toyota", "Land Cruiser Prado", "12355-D-3", "suv", 1200, "diesel", "automatic", 7, 2022, 96000),
    ("Série 5", "BMW", "Série 5", "12356-E-1", "luxury", 1500, "diesel", "automatic", 5, 2024, 15000),
    ("Classe E", "Mercedes", "Classe E", "12357-E-2", "luxury", 1650, "diesel", "automatic", 5, 2023, 31000),
    ("Range Rover", "Land Rover", "Range Rover Velar", "12358-E-3", "luxury", 2200, "diesel", "automatic", 5, 2023, 42000),
    ("Model 3", "Tesla", "Model 3", "12359-E-4", "luxury", 1400, "electric", "automatic", 5, 2024, 12000),
]

CLIENTS = [
    ("Ahmed El Fassi", "+212 661 111 111", "+212 661 111 111", "Maroc", "Marrakech", "AA123456", "BE123456"),
    ("Fatima Zahra Idrissi", "+212 662 222 222", "", "Maroc", "Casablanca", "BB654321", "CC789012"),
    ("Mohamed Tazi", "+212 663 333 333", "+212 663 333 333", "Maroc", "Rabat", "CC111222", "DD333444"),
    ("Yassine Berrada", "+212 664 444 444", "", "Maroc", "Fès", "DD555666", "EE777888"),
    ("Sophie Durand", "+33 6 12 34 56 78", "+33 6 12 34 56 78", "France", "Paris", "", "12AB34567"),
    ("James Whitfield", "+44 7700 900123", "", "Royaume-Uni", "Londres", "", "GB9876543"),
    ("Carmen Ruiz", "+34 612 345 678", "+34 612 345 678", "Espagne", "Madrid", "", "X1234567"),
    ("Hans Müller", "+49 151 23456789", "", "Allemagne", "Munich", "", "DE5566778"),
    ("Elena Rossi", "+39 333 123 4567", "+39 333 123 4567", "Italie", "Milan", "", "IT9988776"),
    ("David Johnson", "+1 415 555 0198", "", "États-Unis", "San Francisco", "", "US1122334"),
]

PICKUP_LOCATIONS = [
    "Aéroport Marrakech-Menara",
    "Centre-ville (Jemaa el-Fna)",
    "Gare Marrakech",
    "Hôtel de l'agence partenaire",
]

OPTION_TYPES = [
    BookingOption.OptionType.GPS,
    BookingOption.OptionType.CHILD_SEAT,
    BookingOption.OptionType.ADDITIONAL_DRIVER,
    BookingOption.OptionType.INSURANCE_FULL,
]

PLACEHOLDER_COLORS = [
    (37, 99, 235), (16, 185, 129), (245, 158, 11),
    (139, 92, 246), (239, 68, 68), (20, 184, 166),
]


class Command(BaseCommand):
    help = "Populate the CRM with realistic demo data (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Hard-delete existing CRM business data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(20260923)  # reproducible demo data

        if options["fresh"]:
            self._wipe()
            self.stdout.write(self.style.WARNING("Existing CRM data removed."))

        users = self._create_users()
        self._create_company_settings()
        categories = self._create_categories()
        cars = self._create_cars(categories, actor=users["admin"])
        clients = self._create_clients(actor=users["employee"])
        self._create_promotions(actor=users["admin"])
        bookings = self._create_bookings(cars=cars, clients=clients, users=users)
        self._create_invoices(bookings=bookings, actor=users["manager"])

        self._report()

    # ------------------------------------------------------------------
    # wipe
    # ------------------------------------------------------------------

    def _wipe(self) -> None:
        """Hard-delete business data (users are kept and re-upserted)."""
        Invoice.all_objects.all().delete()
        Booking.all_objects.all().delete()   # cascades options + edit requests
        Car.all_objects.all().delete()       # cascades images + maintenances
        Client.all_objects.all().delete()
        Promotion.objects.all().delete()
        CompanySettings.objects.all().delete()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sync_translations(instance, **values) -> None:
        """Write per-language fields onto a row that may already exist.

        ``get_or_create(defaults=...)`` never touches rows that are already
        there, so without this a re-run would leave a newly added language (say
        Arabic) unpopulated on a database seeded before that language existed.
        The seed owns the demo content, so these fields are overwritten rather
        than merged; nothing is written when the row already holds these values.
        """
        changed = [field for field, value in values.items() if getattr(instance, field) != value]
        if not changed:
            return
        for field in changed:
            setattr(instance, field, values[field])
        instance.save(update_fields=changed)

    # ------------------------------------------------------------------
    # users / settings / lookups
    # ------------------------------------------------------------------

    def _create_users(self) -> dict[str, User]:
        created: dict[str, User] = {}
        for spec in USERS:
            user, is_new = User.objects.get_or_create(
                email=spec["email"],
                defaults={
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                    "role": spec["role"],
                    "telephone": spec["telephone"],
                    "cin": spec["cin"],
                    "is_staff": spec["is_staff"],
                    "is_superuser": spec["is_superuser"],
                },
            )
            if is_new:
                user.set_password(DEFAULT_PASSWORD)
                user.save()
            key = spec["role"].lower()
            created[key] = user
        return created

    def _create_company_settings(self) -> CompanySettings:
        settings_row = CompanySettings.load()
        settings_row.company_name = "Smart Rent Car Marrakech"
        settings_row.address = "Avenue Mohammed VI, Gueliz\n40000 Marrakech, Maroc"
        settings_row.phone = "+212 524 00 00 00"
        settings_row.email = "contact@smartrentcar.ma"
        settings_row.website = "https://smartrentcar.ma"
        settings_row.ice = "001234567000089"
        settings_row.rc = "RC 87654 Marrakech"
        settings_row.patente = "PA 11223344"
        settings_row.if_number = "IF 44556677"
        settings_row.bank_details = (
            "Attijariwafa Bank — Agence Gueliz\n"
            "RIB : 007 780 0001234567890123 45\n"
            "IBAN : MA64 0077 8000 0123 4567 8901 2345"
        )
        settings_row.default_vat = Decimal("20.00")
        settings_row.invoice_footer = (
            "Merci de votre confiance. Location soumise aux conditions générales "
            "de Smart Rent Car Marrakech."
        )
        settings_row.invoice_footer_ar = (
            "شكرًا لثقتكم. تخضع عملية الكراء للشروط العامة لشركة "
            "Smart Rent Car Marrakech."
        )
        settings_row.invoice_footer_en = (
            "Thank you for your trust. Rentals are subject to the general terms "
            "of Smart Rent Car Marrakech."
        )
        settings_row.default_language = "fr"
        settings_row.save()
        return settings_row

    def _create_categories(self) -> dict[str, CarCategory]:
        result: dict[str, CarCategory] = {}
        for name, text in CATEGORIES:
            category, _ = CarCategory.objects.get_or_create(
                name=name,
                defaults={"description": text["fr"], "description_fr": text["fr"]},
            )
            self._sync_translations(
                category,
                description_fr=text["fr"],
                description_en=text["en"],
                description_ar=text["ar"],
            )
            result[name] = category
        return result

    def _create_promotions(self, *, actor: User) -> None:
        promotions = [
            {
                "code": "BIENVENUE10",
                "descriptions": {
                    "fr": "10 % de remise sur la première location.",
                    "en": "10% off your first rental.",
                    "ar": "خصم 10% على أول عملية كراء.",
                },
                "discount_type": DiscountType.PERCENTAGE,
                "discount_value": Decimal("10.00"),
            },
            {
                "code": "AIRPORT200",
                "descriptions": {
                    "fr": "200 MAD de remise sur les réservations aéroport.",
                    "en": "200 MAD off airport bookings.",
                    "ar": "خصم 200 درهم على الحجوزات من المطار.",
                },
                "discount_type": DiscountType.FIXED,
                "discount_value": Decimal("200.00"),
            },
        ]
        today = timezone.localdate()
        for spec in promotions:
            text = spec["descriptions"]
            promotion, _ = Promotion.objects.get_or_create(
                code=spec["code"],
                defaults={
                    "description": text["fr"],
                    "description_fr": text["fr"],
                    "discount_type": spec["discount_type"],
                    "discount_value": spec["discount_value"],
                    "valid_from": today - timedelta(days=30),
                    "valid_to": today + timedelta(days=180),
                    "is_active": True,
                    "created_by": actor,
                },
            )
            self._sync_translations(
                promotion,
                description_fr=text["fr"],
                description_en=text["en"],
                description_ar=text["ar"],
            )

    # ------------------------------------------------------------------
    # cars
    # ------------------------------------------------------------------

    def _create_cars(self, categories: dict[str, CarCategory], *, actor: User) -> list[Car]:
        cars: list[Car] = []
        for index, row in enumerate(CARS):
            (name, brand, model, plate, category_key, price, fuel, gearbox, seats, year, mileage) = row
            description_fr = f"{brand} {model} — {price} MAD/jour, parfait pour vos trajets au Maroc."
            description_en = f"{brand} {model} — {price} MAD/day, ideal for your trips in Morocco."
            description_ar = f"{brand} {model} — {price} درهم في اليوم، خيار ممتاز لتنقلاتكم بالمغرب."

            existing = Car.all_objects.filter(plate_number=plate).first()
            if existing is not None:
                self._sync_translations(
                    existing,
                    description_fr=description_fr,
                    description_en=description_en,
                    description_ar=description_ar,
                )
                cars.append(existing)
                continue

            car = Car(
                name=name,
                brand=brand,
                model=model,
                plate_number=plate,
                category=categories[category_key],
                price_per_day=Decimal(str(price)),
                status=CarStatus.AVAILABLE,
                fuel_type=fuel,
                transmission=gearbox,
                seats=seats,
                year=year,
                mileage=mileage,
                description=description_fr,
                description_fr=description_fr,
                description_en=description_en,
                description_ar=description_ar,
                created_by=actor,
                updated_by=actor,
            )
            car.save()

            label = f"{brand} {model}"
            car.picture.save(
                f"{slugify(label)}-main.jpg",
                self._placeholder_image(label, PLACEHOLDER_COLORS[index % len(PLACEHOLDER_COLORS)]),
                save=True,
            )
            CarImage.objects.create(
                car=car,
                image=self._placeholder_image(f"{label} (2)", PLACEHOLDER_COLORS[(index + 2) % len(PLACEHOLDER_COLORS)]),
                is_main=False,
            )
            cars.append(car)
        return cars

    @staticmethod
    def _placeholder_image(label: str, color: tuple[int, int, int]) -> ContentFile:
        """Generate a simple JPEG placeholder so the UI has real images."""
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (900, 560), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle([(24, 24), (876, 536)], outline=(255, 255, 255), width=3)
        draw.text((48, 60), label, fill=(255, 255, 255))
        draw.text((48, 90), "Smart Rent Car — photo de démonstration", fill=(235, 235, 235))

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return ContentFile(buffer.getvalue(), name=f"{slugify(label)}.jpg")

    # ------------------------------------------------------------------
    # clients
    # ------------------------------------------------------------------

    def _create_clients(self, *, actor: User) -> list[Client]:
        clients: list[Client] = []
        for name, telephone, whatsapp, country, address, cin, passport in CLIENTS:
            client, _ = Client.objects.get_or_create(
                name=name,
                defaults={
                    "telephone": telephone,
                    "whatsapp": whatsapp,
                    "country": country,
                    "address": address,
                    "id_document": passport or cin,
                    "comment": "Client international." if country != "Maroc" else "",
                    "created_by": actor,
                    "updated_by": actor,
                },
            )
            clients.append(client)
        return clients

    # ------------------------------------------------------------------
    # bookings
    # ------------------------------------------------------------------

    def _create_bookings(self, *, cars: list[Car], clients: list[Client], users: dict[str, User]) -> list[Booking]:
        """Create 20 bookings across all statuses.

        Constraints honoured:

        * Two bookings for the **same car** never overlap while either of them
          is in a blocking status (pending / confirmed / ongoing) — enforced by
          ``services.create_booking``.
        * Bookings that *do* overlap in time use **different** cars, which is
          what "the fleet is busy" looks like in reality.
        * A handful of cancelled/completed bookings deliberately reuse a car
          whose window is also booked elsewhere, showing that non-blocking
          statuses are ignored by the overlap rule.
        """
        actor = users["employee"]
        today = timezone.localdate()
        bookings: list[Booking] = []
        occupied: dict[int, list[tuple]] = {}

        # Offsets are tuned so the dashboard has real "today" activity.
        offsets = [-18, -14, -12, -9, -7, -5, -4, -2, 0, 0, 1, 2, 3, 5, 7, 9, 12, 15, 18, 21]
        durations = [3, 5, 2, 7, 4, 3, 6, 2, 5, 4, 3, 7, 2, 4, 6, 3, 5, 2, 4, 7]

        for index, (offset, duration) in enumerate(zip(offsets, durations)):
            start = today + timedelta(days=offset)
            end = start + timedelta(days=duration)

            if offset + duration < 0:
                status = BookingStatus.COMPLETED
            elif offset <= 0 < offset + duration:
                status = BookingStatus.ONGOING
            elif offset <= 3:
                status = BookingStatus.CONFIRMED
            else:
                status = BookingStatus.PENDING

            # Two cancellations and one early completion for status variety.
            if index in (7, 16):
                status = BookingStatus.CANCELLED
            if index == 4:
                status = BookingStatus.COMPLETED

            car = self._pick_free_car(cars, occupied, start, end, index)
            client = clients[index % len(clients)]

            data = {
                "car": car,
                "client": client,
                "start_date": start,
                "end_date": end,
                "status": status,
                "pickup_location": PICKUP_LOCATIONS[index % len(PICKUP_LOCATIONS)],
                "return_location": PICKUP_LOCATIONS[(index + 1) % len(PICKUP_LOCATIONS)],
                "notes": "" if index % 3 else "Client à contacter la veille pour confirmation.",
            }

            options = []
            if index % 2 == 0:
                options.append(
                    {
                        "option_type": OPTION_TYPES[index % len(OPTION_TYPES)],
                        "price": Decimal("50.00"),
                        "quantity": 1,
                    }
                )
            if index % 5 == 0:
                options.append(
                    {
                        "option_type": BookingOption.OptionType.INSURANCE_FULL,
                        "price": Decimal("120.00"),
                        "quantity": duration,
                    }
                )

            try:
                booking = booking_services.create_booking(
                    data=data, options=options, actor=actor
                )
            except Exception as exc:  # noqa: BLE001 - seed robustness
                self.stderr.write(f"  ! booking #{index} skipped: {exc}")
                continue

            bookings.append(booking)
            if booking.blocks_availability:
                occupied.setdefault(car.pk, []).append((start, end, booking.pk))

        return bookings

    @staticmethod
    def _pick_free_car(
        cars: list[Car],
        occupied: dict[int, list[tuple]],
        start,
        end,
        index: int,
    ) -> Car:
        """Round-robin over the fleet, skipping cars already taken in the window."""
        for offset in range(len(cars)):
            candidate = cars[(index + offset) % len(cars)]
            windows = occupied.get(candidate.pk, [])
            if not any(start <= w_end and end >= w_start for w_start, w_end, _ in windows):
                return candidate
        # Every car is busy in this window; reuse the round-robin pick and let
        # the service raise, which keeps the demo data honest.
        return cars[index % len(cars)]

    # ------------------------------------------------------------------
    # invoices
    # ------------------------------------------------------------------

    def _create_invoices(self, *, bookings: list[Booking], actor: User) -> None:
        """Issue invoices for completed bookings (with a promo on some)."""
        promotion = Promotion.objects.filter(code="BIENVENUE10").first()
        issued = 0
        for index, booking in enumerate(bookings):
            if booking.status != BookingStatus.COMPLETED or hasattr(booking, "invoice"):
                continue
            try:
                invoice_services.issue_invoice(
                    booking=booking,
                    actor=actor,
                    promotion=promotion if index % 3 == 0 else None,
                )
            except Exception as exc:  # noqa: BLE001 - seed robustness
                self.stderr.write(f"  ! invoice for booking #{booking.pk} skipped: {exc}")
            else:
                issued += 1
        self._invoices_issued = issued

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------

    def _report(self) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"  Users      : {User.objects.count()}  (password: {DEFAULT_PASSWORD})")
        self.stdout.write(f"  Categories : {CarCategory.objects.count()}")
        self.stdout.write(f"  Cars       : {Car.objects.count()}")
        self.stdout.write(f"  Clients    : {Client.objects.count()}")
        self.stdout.write(f"  Bookings   : {Booking.objects.count()}")
        self.stdout.write(f"  Invoices   : {Invoice.objects.count()}")
        self.stdout.write(f"  Promotions : {Promotion.objects.count()}")
        self.stdout.write("")
        self.stdout.write("  Login with: admin@smartrent.ma / manager@smartrent.ma / employe@smartrent.ma")
