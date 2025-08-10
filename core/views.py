from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication

from .models import Device
from .serializers import DeviceConfigSerializer

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