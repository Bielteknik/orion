from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
import json

from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication

# Modelleri import ediyoruz
from .models import Alert, Device, Sensor, SensorReading

# TÜM serializer'ları tek bir yerden, doğru dosyadan import ediyoruz
from .serializers import (
    DeviceConfigSerializer, 
    SensorReadingSerializer,
    DeviceSerializer,
    SensorSerializer
)

# Kural motorunu import ediyoruz
from .rule_engine import process_rules_for_reading


# --- API Endpoints ---

class DeviceConfigView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        try:
            device = request.user.device
            serializer = DeviceConfigSerializer(device)
            return Response(serializer.data)
        except Device.DoesNotExist:
            return Response({"error": "Bu token'a ait bir cihaz bulunamadı."}, status=status.HTTP_404_NOT_FOUND)

class SubmitReadingView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        serializer = SensorReadingSerializer(data=request.data)
        if serializer.is_valid():
            sensor_instance = serializer.validated_data['sensor']
            if sensor_instance.device != request.user.device:
                return Response({"error": "Yetkisiz işlem."}, status=status.HTTP_403_FORBIDDEN)
            saved_reading = serializer.save()
            try:
                process_rules_for_reading(saved_reading)
            except Exception as e:
                print(f"❌ KURAL MOTORU HATASI: {e}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all().order_by('name')
    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated]
    def perform_create(self, serializer):
        device_name = serializer.validated_data.get('name')
        base_username = f"device-{slugify(device_name)}"
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}-{counter}"
            counter += 1
        password = get_random_string(length=12)
        user = User.objects.create_user(username=username, password=password)
        serializer.save(user=user)

class SensorViewSet(viewsets.ModelViewSet):
    serializer_class = SensorSerializer
    permission_classes = [IsAuthenticated]
    queryset = Sensor.objects.select_related('device').all().order_by('name')


# --- Frontend Views ---

class DashboardView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        try:
            device = request.user.device
        except Device.DoesNotExist:
            return render(request, 'dashboard.html', {'error': 'Cihaz bulunamadı.'})
        last_reading = SensorReading.objects.filter(sensor__device=device).order_by('-timestamp').first()
        recent_readings = SensorReading.objects.filter(sensor__device=device).order_by('-timestamp')[:5]
        time_threshold = timezone.now() - timedelta(hours=24)
        readings_for_chart = SensorReading.objects.filter(sensor__device=device, timestamp__gte=time_threshold).order_by('timestamp')
        chart_labels = [r.timestamp.strftime('%H:%M') for r in readings_for_chart]
        chart_temp_data = [r.value.get('temperature') for r in readings_for_chart if r.value and 'temperature' in r.value]
        chart_hum_data = [r.value.get('humidity') for r in readings_for_chart if r.value and 'humidity' in r.value]
        context = {
            'device': device, 'last_reading': last_reading, 'recent_readings': recent_readings,
            'chart_labels': json.dumps(chart_labels), 'chart_temp_data': json.dumps(chart_temp_data),
            'chart_hum_data': json.dumps(chart_hum_data),
        }
        return render(request, 'dashboard.html', context)

class StationsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        all_devices = Device.objects.filter(is_active=True)
        devices_with_readings = []
        for device in all_devices:
            last_reading = SensorReading.objects.filter(sensor__device=device).order_by('-timestamp').first()
            devices_with_readings.append({'device': device, 'last_reading': last_reading})
        context = {'devices_with_readings': devices_with_readings}
        return render(request, 'stations.html', context)

class SensorsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        all_devices = Device.objects.all()
        selected_device_id = request.GET.get('device', None)
        sensors_query = Sensor.objects.select_related('device').filter(is_active=True)
        if selected_device_id:
            sensors_query = sensors_query.filter(device_id=selected_device_id)
        sensors_with_readings = []
        for sensor in sensors_query:
            last_reading = SensorReading.objects.filter(sensor=sensor).order_by('-timestamp').first()
            sensors_with_readings.append({'sensor': sensor, 'last_reading': last_reading})
        context = {
            'all_devices': all_devices, 'sensors_with_readings': sensors_with_readings,
            'selected_device_id': selected_device_id,
            'sensor_interface_choices': Sensor.INTERFACE_CHOICES,
            'sensor_parser_choices': Sensor.PARSER_TYPE_CHOICES,
        }
        return render(request, 'sensors.html', context)

class CamerasView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'cameras.html', {})

class AnalyticsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'analytics.html', {})

class MapView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'interactive_map.html', {})

class AlertsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        # Tüm çözülmemiş (acknowledged=False) uyarıları al
        active_alerts = Alert.objects.filter(is_acknowledged=False).select_related('rule', 'device')
        # Tüm uyarıları (geçmiş) al
        all_alerts = Alert.objects.all().select_related('rule', 'device')[:50] # Son 50 taneyi göster
        
        context = {
            'active_alerts': active_alerts,
            'alert_history': all_alerts,
        }
        return render(request, 'alerts.html', context)

class SettingsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'settings.html', {})