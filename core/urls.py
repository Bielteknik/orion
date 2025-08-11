from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeviceConfigView, 
    SubmitReadingView, 
    DashboardView, 
    StationsView,
    SensorsView,
    DeviceViewSet,
    SensorViewSet,
    CamerasView,
    AnalyticsView,
    MapView,
    AlertsView,
    SettingsView,
    AnalyticsDataView
)

# Router'ı burada tanımlıyoruz, tıpkı daha önce olduğu gibi.
router = DefaultRouter()
router.register(r'devices', DeviceViewSet, basename='device')
router.register(r'sensors', SensorViewSet, basename='sensor')

# TÜM URL'leri tek bir listede birleştiriyoruz.
urlpatterns = [
    # Frontend URL'leri
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('stations/', StationsView.as_view(), name='stations'),
    path('sensors/', SensorsView.as_view(), name='sensors'),
    path('cameras/', CamerasView.as_view(), name='cameras'),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
    path('map/', MapView.as_view(), name='map'),
    path('alerts/', AlertsView.as_view(), name='alerts'),
    path('settings/', SettingsView.as_view(), name='settings'),
    path('analytics/data/', AnalyticsDataView.as_view(), name='analytics-data'),

    # Özel API URL'leri (router'a uymayanlar)
    path('api/v3/device/config/', DeviceConfigView.as_view(), name='api-device-config'),
    path('api/v3/readings/submit/', SubmitReadingView.as_view(), name='api-submit-reading'),
    
    # Router tarafından oluşturulan API URL'leri (/api/v3/devices/, /api/v3/sensors/)
    path('api/v3/', include(router.urls)),
]