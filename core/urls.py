from django.urls import path
from .views import DeviceConfigView, SubmitReadingView # SubmitReadingView'i import et

urlpatterns = [
    path('device/config/', DeviceConfigView.as_view(), name='device-config'),
    path('readings/submit/', SubmitReadingView.as_view(), name='submit-reading'),
]