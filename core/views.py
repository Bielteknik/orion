from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.utils.text import slugify
import json

from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.decorators import action

from .models import Device, Sensor, SensorReading, Rule, Alert, Camera, Command, CameraCapture
from .serializers import *
from .rule_engine import process_rules_for_reading

# --- API Endpoints ---
class DeviceConfigView(APIView):
    authentication_classes = [TokenAuthentication]; permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        try: device = request.user.device; serializer = DeviceConfigSerializer(device); return Response(serializer.data)
        except Device.DoesNotExist: return Response({"error": "Cihaz bulunamadı."}, status=404)

class SubmitReadingView(APIView):
    authentication_classes = [TokenAuthentication]; permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        s = SensorReadingSerializer(data=request.data)
        if s.is_valid():
            si = s.validated_data['sensor']
            if si.device != request.user.device: return Response({"error": "Yetkisiz."}, status=403)
            sr = s.save()
            try: process_rules_for_reading(sr)
            except Exception as e: print(f"❌ KURAL MOTORU HATASI: {e}")
            return Response(s.data, status=201)
        return Response(s.errors, status=400)

class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all().order_by('name'); serializer_class = DeviceSerializer; permission_classes = [IsAuthenticated]
    def perform_create(self, serializer):
        name = serializer.validated_data.get('name'); base = f"device-{slugify(name)}"; username = base; i = 1
        while User.objects.filter(username=username).exists(): username = f"{base}-{i}"; i += 1
        pwd = get_random_string(12); user = User.objects.create_user(username=username, password=pwd); serializer.save(user=user)

class SensorViewSet(viewsets.ModelViewSet):
    serializer_class = SensorSerializer; permission_classes = [IsAuthenticated]; queryset = Sensor.objects.select_related('device').all().order_by('name')

class RuleViewSet(viewsets.ModelViewSet):
    queryset = Rule.objects.prefetch_related('conditions', 'actions').all(); serializer_class = RuleSerializer; permission_classes = [IsAuthenticated]

class CameraViewSet(viewsets.ModelViewSet):
    queryset = Camera.objects.select_related('device').all(); serializer_class = CameraSerializer; permission_classes = [IsAuthenticated]
    @action(detail=True, methods=['post'])
    def capture_photo(self, request, pk=None):
        camera = self.get_object()
        Command.objects.create(device=camera.device, command_type='capture_photo', payload={'camera_id': camera.id, 'rtsp_url': camera.rtsp_url})
        return Response({'status': 'capture command sent'}, status=202)

class CommandViewSet(viewsets.ModelViewSet):
    serializer_class = CommandSerializer; permission_classes = [IsAuthenticated]
    def get_queryset(self): return Command.objects.filter(device=self.request.user.device, is_executed=False)

class CameraCaptureViewSet(viewsets.ModelViewSet):
    queryset = CameraCapture.objects.all(); serializer_class = CameraCaptureSerializer; permission_classes = [IsAuthenticated]

class AnalyticsDataView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]; permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        ids_str = request.query_params.get('sensors', '')
        if not ids_str: return Response({"error": "Sensör seçin."}, status=400)
        try: ids = [int(sid) for sid in ids_str.split(',')]
        except: return Response({"error": "Geçersiz ID."}, status=400)
        period = request.query_params.get('period', '24h'); now = timezone.now()
        if period == '7d': start_time = now - timedelta(days=7)
        elif period == '30d': start_time = now - timedelta(days=30)
        else: start_time = now - timedelta(hours=24)
        qs = SensorReading.objects.filter(sensor_id__in=ids, timestamp__gte=start_time).select_related('sensor', 'sensor__device').order_by('sensor_id', 'timestamp')
        data = {}
        for r in qs:
            if r.sensor_id not in data: data[r.sensor_id] = {'name': r.sensor.name, 'device': r.sensor.device.name, 'readings': []}
            data[r.sensor_id]['readings'].append({'timestamp': r.timestamp, 'value': r.value})
        return Response(data)

# --- Frontend Views ---
class DashboardView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        try: device = request.user.device
        except: return render(request, 'dashboard.html', {'error': 'Cihaz bulunamadı.'})
        # ... (Geri kalanı bir öncekiyle aynı)
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
        devices = Device.objects.filter(is_active=True); data = []
        for d in devices: data.append({'device': d, 'last_reading': SensorReading.objects.filter(sensor__device=d).order_by('-timestamp').first()})
        return render(request, 'stations.html', {'devices_with_readings': data})

class SensorsView(LoginRequiredMixin, View):
    login_url = '/admin/login/';
    def get(self, request):
        did = request.GET.get('device', None)
        qs = Sensor.objects.select_related('device').filter(is_active=True)
        if did: qs = qs.filter(device_id=did)
        data = []
        for s in qs: data.append({'sensor': s, 'last_reading': SensorReading.objects.filter(sensor=s).order_by('-timestamp').first()})
        context = {
            'all_devices': Device.objects.all(), 'sensors_with_readings': data, 'selected_device_id': did,
            'sensor_interface_choices': Sensor.INTERFACE_CHOICES, 'sensor_parser_choices': Sensor.PARSER_TYPE_CHOICES,
        }
        return render(request, 'sensors.html', context)

class CamerasView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        context = {
            'all_cameras': Camera.objects.select_related('device').all(),
            'all_devices': Device.objects.all(),
            'recent_captures': CameraCapture.objects.all()[:6],
            'stats': {
                'active_cameras': Camera.objects.filter(status='active').count(),
                'recording_cameras': Camera.objects.filter(is_recording=True).count(),
                'captures_today': CameraCapture.objects.filter(timestamp__date=timezone.now().date()).count(),
                'storage_used_tb': 0.0
            }
        }
        return render(request, 'cameras.html', context)

class AnalyticsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        return render(request, 'analytics.html', {'all_devices': Device.objects.prefetch_related('sensors').order_by('name')})

class MapView(LoginRequiredMixin, View):
    login_url = '/admin/login/';
    def get(self, request): return render(request, 'interactive_map.html', {})

class AlertsView(LoginRequiredMixin, View):
    login_url = '/admin/login/';
    def get(self, request):
        active_alerts = Alert.objects.filter(is_acknowledged=False).select_related('rule', 'device')
        alert_history = Alert.objects.all().select_related('rule', 'device')[:50]
        context = {
            'all_rules': Rule.objects.all().order_by('name'),
            'all_devices': Device.objects.prefetch_related('sensors').all(),
            'active_alerts': active_alerts, # Bu eksik kalmıştı, ekliyorum
            'alert_history': alert_history,
        }
        return render(request, 'alerts.html', context)
        
class SettingsView(LoginRequiredMixin, View):
    login_url = '/admin/login/';
    def get(self, request): return render(request, 'settings.html', {})