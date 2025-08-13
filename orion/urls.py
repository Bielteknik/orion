from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='stations', permanent=False)),
    #path('', RedirectView.as_view(url='/dashboard/')),
    
    # Tüm frontend ve API isteklerini tek bir include ile core uygulamasına yönlendir.
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)