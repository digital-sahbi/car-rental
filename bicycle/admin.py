from django.contrib import admin
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from .models import Car, Booking

User = get_user_model()


class CustomAdminSite(admin.AdminSite):
    site_header = 'Car Rental Administration'
    site_title = 'Car Rental Admin'
    index_title = 'Dashboard'
    index_template = 'admin/custom_index.html'

    def each_context(self, request):
        context = super().each_context(request)
        today = timezone.now().date()
        context['today_bookings'] = (
            Booking.objects.filter(start_date=today)
            .select_related('car', 'user')
            .order_by('start_date', 'end_date')
        )
        context['future_bookings'] = (
            Booking.objects.filter(start_date__gt=today)
            .select_related('car', 'user')
            .order_by('start_date', 'end_date')
        )
        context['recent_users'] = (
            User.objects.order_by('-date_joined')[:5]
        )
        context['available_cars_count'] = Car.objects.filter(available=True).count()
        return context


admin_site = CustomAdminSite(name='admin')
admin_site.register(User)
admin_site.register(Car)
admin_site.register(Booking)
admin_site.register(Group)
