from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from rest_framework import status

from .models import Device
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