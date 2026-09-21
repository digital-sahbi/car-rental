
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from bicycle.views import login_view, register_view, logout_view
from bicycle.admin import admin_site

urlpatterns=[
 path('admin/', admin_site.urls),
 path('', include('bicycle.urls')),
 path('', include('car.urls')),
]
if settings.DEBUG:
 urlpatterns+=static(settings.MEDIA_URL,document_root=settings.MEDIA_ROOT)
