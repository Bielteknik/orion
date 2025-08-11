from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
import json
from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Max, Min
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework import viewsets, status

from .models import Device, Sensor, SensorReading
from .serializers import DeviceConfigSerializer, SensorReadingSerializer, DeviceSerializer, SensorSerializer

from .rule_engine import process_rules_for_reading
from core import serializers

class DeviceConfigView(APIView):
    """
    İstek yapan cihaza ait yapılandırma bilgilerini döndüren API endpoint'i.
    Kimlik doğrulama için HTTP Header'ında 'Authorization: Token <token_anahtari>' beklenir.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            # TokenAuthentication sayesinde, geçerli bir token ile istek yapıldığında
            # o token'ın sahibi olan kullanıcı nesnesi request.user'a atanır.
            # Device modelindeki OneToOneField sayesinde de o kullanıcıya bağlı
            # cihazı request.user.device ile kolayca buluruz.
            device = request.user.device
            serializer = DeviceConfigSerializer(device)
            return Response(serializer.data)
        except Device.DoesNotExist:
            return Response({"error": "Bu token'a ait bir cihaz bulunamadı."}, status=404)

class SubmitReadingView(APIView):
    """
    İstemciden gelen sensör okumalarını kabul eden, kaydeden ve
    kural motorunu tetikleyen API endpoint'i.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = SensorReadingSerializer(data=request.data)
        
        if serializer.is_valid():
            # Güvenlik Kontrolü: İstek yapan cihaz, bu sensörün sahibi mi?
            sensor_instance = serializer.validated_data['sensor']
            if sensor_instance.device != request.user.device:
                return Response(
                    {"error": "Yetkisiz işlem. Bu sensör, istek yapan cihaza ait değil."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Veriyi veritabanına kaydet
            saved_reading = serializer.save()

            # --- KURAL MOTORUNU TETİKLE ---
            # Veri kaydedildikten hemen sonra, bu yeni okuma için kuralları işle.
            try:
                process_rules_for_reading(saved_reading)
            except Exception as e:
                # Kural motorunda bir hata olursa, API'nin çökmesini engelle.
                # Hatayı sunucu konsoluna yazdır.
                print(f"❌ KURAL MOTORU HATASI: {e}")
            
            # Başarılı yanıtı, kaydedilen veriyle birlikte geri döndür
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            # Gelen veri geçerli değilse hataları döndür
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DashboardView(LoginRequiredMixin, View):
    login_url = '/admin/login/'

    def get(self, request):
        # Sadece giriş yapmış kullanıcının kendi cihazını göstermesi için
        # Eğer admin tüm cihazları görecekse, bu mantık değişebilir.
        # Şimdilik, her kullanıcı sadece kendi cihazını görür.
        try:
            device = request.user.device
        except Device.DoesNotExist:
            # Kullanıcıya atanmış bir cihaz yoksa boş bir sayfa gösterilebilir.
            return render(request, 'dashboard.html', {'error': 'Cihaz bulunamadı.'})

        # --- Veri Çekme İşlemleri ---
        
        # 1. Son okumayı al (Sıcaklık kartı için)
        last_reading = SensorReading.objects.filter(sensor__device=device).order_by('-timestamp').first()

        # 2. Son 5 okumayı al (Sağdaki "Son Ölçümler" listesi için)
        recent_readings = SensorReading.objects.filter(sensor__device=device).order_by('-timestamp')[:5]

        # 3. Son 24 saatlik veriyi al (Grafik için)
        time_threshold = timezone.now() - timedelta(hours=24)
        readings_for_chart = SensorReading.objects.filter(
            sensor__device=device,
            timestamp__gte=time_threshold
        ).order_by('timestamp')

        # 4. Grafik için verileri hazırla
        # Verileri JSON formatında ve güvenli bir şekilde şablona aktaracağız.
        chart_labels = [r.timestamp.strftime('%H:%M') for r in readings_for_chart]
        # value içindeki 'temperature' ve 'humidity' anahtarlarının varlığını kontrol et
        chart_temp_data = [r.value.get('temperature') for r in readings_for_chart if 'temperature' in r.value]
        chart_hum_data = [r.value.get('humidity') for r in readings_for_chart if 'humidity' in r.value]

        # --- Context'i Hazırla ---
        # Bu sözlük, şablona göndereceğimiz tüm verileri içerir.
        context = {
            'device': device,
            'last_reading': last_reading,
            'recent_readings': recent_readings,
            'chart_labels': json.dumps(chart_labels),
            'chart_temp_data': json.dumps(chart_temp_data),
            'chart_hum_data': json.dumps(chart_hum_data),
        }
        
        return render(request, 'dashboard.html', context)
    
class StationsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'

    def get(self, request):
        # Tüm aktif cihazları veritabanından çekelim.
        all_devices = Device.objects.filter(is_active=True)
        
        devices_with_readings = []
        for device in all_devices:
            # Her cihazın son sensör okumasını bulalım.
            last_reading = SensorReading.objects.filter(sensor__device=device).order_by('-timestamp').first()
            devices_with_readings.append({
                'device': device,
                'last_reading': last_reading
            })

        context = {
            'devices_with_readings': devices_with_readings
        }
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
            sensors_with_readings.append({
                'sensor': sensor,
                'last_reading': last_reading
            })
        context = {
            'all_devices': all_devices,
            'sensors_with_readings': sensors_with_readings,
            'selected_device_id': selected_device_id,
            # YENİ: Modeldaki seçenekleri şablona gönder
            'sensor_interface_choices': Sensor.INTERFACE_CHOICES,
            'sensor_parser_choices': Sensor.PARSER_TYPE_CHOICES,
        }
        return render(request, 'sensors.html', context)

class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    # Bu view'e sadece admin panelinden giriş yapmış (staff) kullanıcılar erişebilir.
    # permission_classes = [permissions.IsAdminUser] 
    # Şimdilik tüm yetkili kullanıcılar erişsin:
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        """ Yeni bir cihaz oluşturulurken otomatik olarak bir kullanıcı da oluşturur. """
        device_name = serializer.validated_data.get('name')
        
        # 1. Benzersiz bir kullanıcı adı oluştur
        base_username = f"device_{device_name.lower().replace(' ', '_').replace('-', '_')}"
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
        
        # 2. Yeni kullanıcıyı oluştur
        # DÜZELTME: get_random_string ile güvenli bir şifre oluşturuyoruz.
        password = get_random_string(length=12)
        user = User.objects.create_user(username=username, password=password)

        # 3. Cihazı bu yeni kullanıcıya atayarak kaydet
        serializer.save(user=user)

class SensorViewSet(viewsets.ModelViewSet):
    serializer_class = SensorSerializer
    permission_classes = [IsAuthenticated]
    queryset = Sensor.objects.select_related('device').all().order_by('name')
    
class CamerasView(LoginRequiredMixin, View):
    login_url = '/admin/login/'

    def get(self, request):
        # Gelecekte burada veritabanından kamera bilgilerini çekeceğiz.
        # Şimdilik boş bir context gönderiyoruz.
        context = {}
        return render(request, 'cameras.html', context)

class AnalyticsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'

    def get(self, request):
        # Gelecekte burada veritabanından analiz için veri çekeceğiz.
        context = {}
        return render(request, 'analytics.html', context)

class MapView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        context = {}
        return render(request, 'interactive_map.html', context)

class AlertsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        context = {}
        return render(request, 'alerts.html', context)

class SettingsView(LoginRequiredMixin, View):
    login_url = '/admin/login/'
    def get(self, request):
        context = {}
        return render(request, 'settings.html', context)