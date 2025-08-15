import datetime
from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.utils.text import slugify
import json
from datetime import datetime, timedelta
from django.db.models import Avg, Max, Min, StdDev, Variance

from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.decorators import action
from urllib3 import request

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
    
    @action(detail=True, methods=['post'])
    def toggle_recording(self, request, pk=None):
        camera = self.get_object()
        camera.is_recording = not camera.is_recording
        camera.save(update_fields=['is_recording'])
        return Response({'status': 'recording toggled', 'is_recording': camera.is_recording})    

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

    def get(self, request, device_id):
        try:
            # URL'den gelen ID'ye göre istenen cihazı ve ilişkili modellerini al
            target_device = Device.objects.prefetch_related('sensors', 'cameras').get(id=device_id)
        except Device.DoesNotExist:
            return render(request, 'error.html', {'message': 'İstasyon bulunamadı.'})

        # Sayfanın üst kısmındaki istasyon değiştirme menüsü için diğer tüm cihazlar
        all_devices_for_nav = Device.objects.exclude(id=device_id).order_by('name')
        active_sensors = target_device.sensors.filter(is_active=True)
        sensors_for_cards = active_sensors[:4] # Sadece ilk 4 aktif sensör
        sensor_card_data = []
        for sensor in sensors_for_cards:
            sensor_card_data.append({
                'sensor': sensor,
                'reading': SensorReading.objects.filter(sensor=sensor).order_by('-timestamp').first()
            })
        
        # Grid'i her zaman 4 elemana tamamla
        num_existing_cards = len(sensor_card_data)
        num_placeholders = 4 - num_existing_cards
        if num_placeholders > 0:
            sensor_card_data.extend([None] * num_placeholders)
        
        # Sayfanın altındaki "Sensör Verileri Listesi" için geçmiş okumalar
        filter_date_str = request.GET.get('filter_date')
        reading_history = SensorReading.objects.filter(sensor__device=target_device).select_related('sensor')

        if filter_date_str:
            try:
                # Gelen string'i tarih nesnesine çevir ve o güne ait kayıtları filtrele
                filter_date = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
                reading_history = reading_history.filter(timestamp__date=filter_date)
            except (ValueError, TypeError):
                # Geçersiz tarih formatı gelirse, filtreleme yapma
                pass
        
        # Sonuçları zaman damgasına göre sırala ve ilk 50'sini al
        reading_history = reading_history.order_by('-timestamp')[:50]

        # Şablona gönderilecek olan tüm verileri tek bir yerde topla
        context = {
            'device': target_device,
            'all_devices_for_nav': all_devices_for_nav,
            'sensor_cards': sensor_card_data,
            'main_camera': target_device.cameras.order_by('name').first(),
            'reading_history': reading_history,
            'captures_today_count': CameraCapture.objects.filter(
                camera__device=target_device, 
                timestamp__date=timezone.now().date()
            ).count(),
            'today_date': timezone.now().strftime('%Y-%m-%d'),
            'filtered_date': filter_date_str,
            # YENİ: Toplam aktif sensör sayısını da şablona gönderelim
            'active_sensor_count': active_sensors.count(), 
            # YENİ: Eğer 4'ten fazla sensör varsa, tüm aktif sensörleri de gönderelim
            'all_active_sensors': active_sensors if active_sensors.count() > 4 else None,            
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
        all_devices = Device.objects.all()
        selected_device_id = request.GET.get('device', None)
        sensors_query = Sensor.objects.select_related('device').all()    
        if selected_device_id:
            sensors_query = sensors_query.filter(device_id=selected_device_id)

        sensors_with_readings = []
        for sensor in sensors_query:
            last_reading = SensorReading.objects.filter(sensor=sensor).order_by('-timestamp').first()
            sensors_with_readings.append({
                'sensor': sensor,
                'last_reading': last_reading
            })
        context = {
            'all_devices': all_devices,
            'sensors_with_readings': sensors_with_readings,
            'selected_device_id': selected_device_id,
            'sensor_interface_choices': Sensor.INTERFACE_CHOICES,
            'sensor_parser_choices': Sensor.PARSER_TYPE_CHOICES,
        }
        return render(request, 'sensors.html', context)

class CamerasView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        all_cameras = Camera.objects.select_related('device').all()
        # Her kameranın cihazının son sensör verisini bir sözlükte toplayalım
        all_readings = {}
        for cam in all_cameras:
            if cam.device_id not in all_readings:
                lr = SensorReading.objects.filter(sensor__device_id=cam.device_id).order_by('-timestamp').first()
                if lr: all_readings[cam.device_id] = lr        
        context = {
            'all_cameras': all_cameras,
            'all_devices': Device.objects.all(),
            'recent_captures': CameraCapture.objects.all()[:6],
            'all_camera_readings': all_readings, # Yeni context değişkeni
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

class SensorDetailDataView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        try:
            sensor = Sensor.objects.get(pk=pk)
        except Sensor.DoesNotExist:
            return Response({"error": "Sensör bulunamadı."}, status=status.HTTP_404_NOT_FOUND)

        period = request.query_params.get('period', '24h')
        now = timezone.now()
        if period == '7d': start_time = now - timedelta(days=7)
        else: start_time = now - timedelta(hours=24)

        # 1. Ham veriyi veritabanından çekelim
        readings = SensorReading.objects.filter(
            sensor=sensor, 
            timestamp__gte=start_time
        ).order_by('timestamp').values('timestamp', 'value')
        
        if not readings:
            return Response({
                'sensor_info': SensorSerializer(sensor).data,
                'stats': {}, 'chart_data': {}
            })

        # 2. Veriyi ve istatistikleri Python içinde işleyelim
        stats = {}
        chart_data = {}
        
        # readings listesindeki her bir okumayı gez
        for reading in readings:
            if not isinstance(reading['value'], dict): continue
            
            # Okumanın içindeki her bir anahtar/değer çiftini işle (örn: 'temperature', 'humidity')
            for key, value in reading['value'].items():
                # Sadece sayısal değerlerle ilgilen
                if not isinstance(value, (int, float)): continue

                # Eğer bu anahtar için listeler daha önce oluşturulmadıysa, şimdi oluştur
                if key not in stats:
                    stats[key] = []
                if key not in chart_data:
                    chart_data[key] = []

                # Değeri istatistik listesine ekle
                stats[key].append(value)
                # Grafiğe uygun formatta veriyi ekle
                chart_data[key].append({
                    'timestamp': reading['timestamp'],
                    f'value__{key}': value
                })

        # 3. İstatistikleri hesapla
        final_stats = {}
        for key, value_list in stats.items():
            if value_list:
                final_stats[key] = {
                    'min_val': min(value_list),
                    'max_val': max(value_list),
                    'avg_val': sum(value_list) / len(value_list),
                }

        response_data = {
            'sensor_info': SensorSerializer(sensor).data,
            'stats': final_stats,
            'chart_data': chart_data,
        }
        return Response(response_data)