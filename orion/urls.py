from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

# YENİ: Gerekli importları ekliyoruz
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/')),
    path('', include('core.urls')),
    path('api/v3/', include('core.urls.api_patterns')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)