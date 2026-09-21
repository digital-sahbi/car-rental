from django.urls import path
from .views import *
urlpatterns = [
    path('', home, name='home'),
    path('login/', login_view, name='login'),
    path('register/', register_view, name='register'),
    path('logout/', logout_view, name='logout'),
    path('book/<int:car_id>/', book_car, name='book_car'),
    path('bookings/', booking_list, name='booking_list'),
    path('bookings/<int:booking_id>/', booking_detail, name='booking_detail'),
    path('bookings/<int:booking_id>/edit/', booking_edit, name='booking_edit'),
]
