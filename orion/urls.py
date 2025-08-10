from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v3/', include('core.urls')),
    
    # Ana sayfa (kök URL) istendiğinde, /dashboard/ adresine yönlendir.
    path('', RedirectView.as_view(url='/dashboard/')),
    
    # Dashboard URL'sini de core.urls'den alıyoruz.
    path('', include('core.urls')),
]