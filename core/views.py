from django.db.models import Q
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
from rest_framework.authentication import TokenAuthentication, SessionAuthentication

# Modelleri import ediyoruz
from .models import Alert, Camera, Device, Rule, Sensor, SensorReading, Condition, Action

# TÜM serializer'ları tek bir yerden, doğru dosyadan import ediyoruz
from .serializers import (
    CameraSerializer,
    DeviceConfigSerializer, 
    SensorReadingSerializer,
    DeviceSerializer,
    SensorSerializer,
    RuleSerializer,
    CameraSerializer,
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

class RuleViewSet(viewsets.ModelViewSet):
    """
    Kuralları, koşulları ve eylemleri yönetmek için API endpoint'leri.
    """
    queryset = Rule.objects.prefetch_related('conditions', 'actions').all()
    serializer_class = RuleSerializer
    permission_classes = [IsAuthenticated]

class CamerasView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        context = {
            'all_cameras': Camera.objects.select_related('device').all(),
            'all_devices': Device.objects.all(),
        }
        return render(request, 'cameras.html', context)

class AnalyticsDataView(APIView):
    """
    Veri analizi sayfası için dinamik olarak filtrelenmiş
    sensör okuma verilerini döndüren API endpoint'i.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        sensor_ids_str = request.query_params.get('sensors', '')
        if not sensor_ids_str:
            return Response({"error": "Lütfen en az bir sensör seçin."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            sensor_ids = [int(sid) for sid in sensor_ids_str.split(',')]
        except (ValueError, TypeError):
            return Response({"error": "Geçersiz sensör ID formatı."}, status=status.HTTP_400_BAD_REQUEST)

        period = request.query_params.get('period', '24h')
        now = timezone.now()
        if period == '7d': start_time = now - timedelta(days=7)
        elif period == '30d': start_time = now - timedelta(days=30)
        else: start_time = now - timedelta(hours=24)
        
        queryset = SensorReading.objects.filter(sensor_id__in=sensor_ids, timestamp__gte=start_time).select_related('sensor', 'sensor__device').order_by('sensor_id', 'timestamp')
        data_by_sensor = {}
        for reading in queryset:
            sensor_id = reading.sensor_id
            if sensor_id not in data_by_sensor:
                data_by_sensor[sensor_id] = { 'name': reading.sensor.name, 'device': reading.sensor.device.name, 'readings': [] }
            data_by_sensor[sensor_id]['readings'].append({ 'timestamp': reading.timestamp, 'value': reading.value })
        return Response(data_by_sensor)

class MapView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'interactive_map.html', {})

class AlertsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        context = {
            'all_rules': Rule.objects.all().order_by('name'),
            'all_devices': Device.objects.prefetch_related('sensors').all(),
            'alert_history': Alert.objects.all()[:50],
        }
        return render(request, 'alerts.html', context)

class SettingsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'settings.html', {})

class AnalyticsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        all_devices = Device.objects.prefetch_related('sensors').order_by('name')
        context = {
            'all_devices': all_devices,
        }
        return render(request, 'analytics.html', context)

class CameraViewSet(viewsets.ModelViewSet):
    queryset = Camera.objects.select_related('device').all()
    serializer_class = CameraSerializer
    permission_classes = [IsAuthenticated]

