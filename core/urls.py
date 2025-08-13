# core/urls.py dosyasının NİHAİ, BASİTLEŞTİRİLMİŞ ve TAM HALİ

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from core import camera_stream
from .views import (
    DeviceConfigView, SubmitReadingView, DashboardView, StationsView,
    SensorsView, CamerasView, AnalyticsView, MapView, AlertsView, SettingsView,
    DeviceViewSet, SensorViewSet, RuleViewSet, CameraViewSet, CommandViewSet, 
    CameraCaptureViewSet, AnalyticsDataView
)

# Router'ımızı oluşturuyoruz
api_router = DefaultRouter()
api_router.register(r'devices', DeviceViewSet, basename='device')
api_router.register(r'sensors', SensorViewSet, basename='sensor')
api_router.register(r'rules', RuleViewSet, basename='rule')
api_router.register(r'cameras', CameraViewSet, basename='camera')
api_router.register(r'commands', CommandViewSet, basename='command')
api_router.register(r'captures', CameraCaptureViewSet, basename='capture')

# TÜM URL'leri tek bir listede birleştiriyoruz.
urlpatterns = [
    # Frontend (Arayüz) URL'leri
    #path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('stations/<uuid:device_id>/dashboard/', DashboardView.as_view(), name='dashboard'),
    path('stations/', StationsView.as_view(), name='stations'),
    path('sensors/', SensorsView.as_view(), name='sensors'),
    path('cameras/', CamerasView.as_view(), name='cameras'),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
    path('map/', MapView.as_view(), name='map'),
    path('alerts/', AlertsView.as_view(), name='alerts'),
    path('settings/', SettingsView.as_view(), name='settings'),
    
    # Kamera yayını için özel URL
    path('cameras/<int:pk>/feed/', camera_stream.camera_feed, name='camera-feed'),


    # API URL'leri (tümü /api/v3/ önekiyle başlayacak)
    path('api/v3/device/config/', DeviceConfigView.as_view(), name='api-device-config'),
    path('api/v3/readings/submit/', SubmitReadingView.as_view(), name='api-submit-reading'),
    path('api/v3/analytics/data/', AnalyticsDataView.as_view(), name='api-analytics-data'),
    
    # Router tarafından oluşturulan tüm API URL'lerini (/api/v3/devices/, vb.) dahil et
    path('api/v3/', include(api_router.urls)),
]