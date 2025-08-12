from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeviceConfigView, SubmitReadingView, DashboardView, StationsView,
    SensorsView, CamerasView, AnalyticsView, MapView, AlertsView, SettingsView,
    DeviceViewSet, SensorViewSet, RuleViewSet, CameraViewSet, CommandViewSet, 
    CameraCaptureViewSet, AnalyticsDataView
)

# --- API URL'leri ---
api_router = DefaultRouter()
api_router.register(r'devices', DeviceViewSet, basename='device')
api_router.register(r'sensors', SensorViewSet, basename='sensor')
api_router.register(r'rules', RuleViewSet, basename='rule')
api_router.register(r'cameras', CameraViewSet, basename='camera')
api_router.register(r'commands', CommandViewSet, basename='command')
api_router.register(r'captures', CameraCaptureViewSet, basename='capture')

api_patterns = [
    path('', include(api_router.urls)),
    path('device/config/', DeviceConfigView.as_view(), name='api-device-config'),
    path('readings/submit/', SubmitReadingView.as_view(), name='api-submit-reading'),
    path('analytics/data/', AnalyticsDataView.as_view(), name='api-analytics-data'),
]

# --- Frontend URL'leri ---
urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('stations/', StationsView.as_view(), name='stations'),
    path('sensors/', SensorsView.as_view(), name='sensors'),
    path('cameras/', CamerasView.as_view(), name='cameras'),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
    path('map/', MapView.as_view(), name='map'),
    path('alerts/', AlertsView.as_view(), name='alerts'),
    path('settings/', SettingsView.as_view(), name='settings'),
]