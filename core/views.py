from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Max, Min
import json
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework import status

from .models import Device, Sensor, SensorReading
from .serializers import DeviceConfigSerializer, SensorReadingSerializer

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
    İstemciden gelen sensör okumalarını kabul eden API endpoint'i.
    İstek formatı: {"sensor": <sensor_id>, "value": {"key": "value"}}
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

            # KURAL MOTORU BURADA ÇALIŞACAK (Şimdilik pas geçiyoruz)
            # print(f"Kural motoru tetiklenecek: {saved_reading.id}")
            
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