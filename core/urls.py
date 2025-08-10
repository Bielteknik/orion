from django.urls import path
from .views import DeviceConfigView

urlpatterns = [
    path('device/config/', DeviceConfigView.as_view(), name='device-config'),
]