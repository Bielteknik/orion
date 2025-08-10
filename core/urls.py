from django.urls import path
from .views import DeviceConfigView, SubmitReadingView, DashboardView # DashboardView'i import et

urlpatterns = [
    # API URLs
    path('device/config/', DeviceConfigView.as_view(), name='api-device-config'),
    path('readings/submit/', SubmitReadingView.as_view(), name='api-submit-reading'),

    # Frontend (Dashboard) URL
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
]