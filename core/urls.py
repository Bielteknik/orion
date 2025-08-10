from django.urls import path
from .views import DeviceConfigView, SubmitReadingView, DashboardView, StationsView, SensorsView

urlpatterns = [
    # API URLs
    path('device/config/', DeviceConfigView.as_view(), name='api-device-config'),
    path('readings/submit/', SubmitReadingView.as_view(), name='api-submit-reading'),

    # Frontend (Dashboard) URL
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('stations/', StationsView.as_view(), name='stations'),
    path('sensors/', SensorsView.as_view(), name='sensors'),    
]