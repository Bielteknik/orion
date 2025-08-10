from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Gelen isteklerde /api/v3/ ile başlayanları core/urls.py'ye yönlendir.
    path('api/v3/', include('core.urls')),
]