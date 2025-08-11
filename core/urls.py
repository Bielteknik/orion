from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DeviceConfigView, SubmitReadingView, DashboardView, StationsView, SensorsView, DeviceViewSet

# ViewSet'ler için bir router oluşturuyoruz.
# Bu, /api/v3/devices/ ve /api/v3/devices/<id>/ gibi URL'leri otomatik oluşturur.
router = DefaultRouter()
router.register(r'devices', DeviceViewSet, basename='device')

urlpatterns = [
    # API URLs
    path('device/config/', DeviceConfigView.as_view(), name='api-device-config'),
    path('readings/submit/', SubmitReadingView.as_view(), name='api-submit-reading'),

    # Frontend (Dashboard) URL
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('stations/', StationsView.as_view(), name='stations'),
    path('sensors/', SensorsView.as_view(), name='sensors'),

    # Router tarafından oluşturulan API URL'lerini ekle
    path('api/v3/', include(router.urls)),       
]