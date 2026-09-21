from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .models import Car, Booking
from datetime import datetime


@login_required
def booking_list(request):
    bookings = Booking.objects.select_related('car', 'user').order_by('start_date')
    return render(request, 'booking_list.html', {'bookings': bookings})


@login_required
def booking_detail(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_related('car', 'user'), id=booking_id)
    return render(request, 'booking_detail.html', {'booking': booking})


@login_required
def booking_edit(request, booking_id):
    booking = get_object_or_404(Booking.objects.select_related('car', 'user'), id=booking_id)
    if request.method == 'POST':
        start = datetime.strptime(request.POST['start_date'], '%Y-%m-%d').date()
        end = datetime.strptime(request.POST['end_date'], '%Y-%m-%d').date()
        booking.start_date = start
        booking.end_date = end
        booking.total_price = (end - start).days + 1
        booking.total_price = booking.total_price * booking.car.price_per_day
        booking.save()
        return redirect('booking_detail', booking_id=booking.id)
    return render(request, 'booking_edit.html', {'booking': booking})

def login_view(request):
    if request.method == 'POST':
        user = authenticate(request, username=request.POST['username'], password=request.POST['password'])
        if user:
            login(request, user)
            return redirect('home')
    return render(request, 'login.html')

def register_view(request):
    if request.method == 'POST':
        User.objects.create_user(
            username=request.POST['username'],
            email=request.POST['email'],
            password=request.POST['password1']
        )
        return redirect('login')
    return render(request, 'register.html')

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def home(request):
    return render(request, 'index.html', {'cars': Car.objects.filter(available=True)})

@login_required
def book_car(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    if request.method == 'POST':
        start = datetime.strptime(request.POST['start_date'], '%Y-%m-%d').date()
        end = datetime.strptime(request.POST['end_date'], '%Y-%m-%d').date()
        days = (end - start).days + 1
        Booking.objects.create(
            user=request.user,
            car=car,
            start_date=start,
            end_date=end,
            total_price=days * car.price_per_day
        )
        return redirect('home')
    return render(request, 'booking.html', {'car': car})
