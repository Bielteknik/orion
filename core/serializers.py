from rest_framework import serializers
from .models import Device, Sensor, SensorReading

# --- API Konfigürasyonu için Serializer'lar ---
# Agent'ın başlangıçta konfigürasyon çekmesi için kullanılır.
class SensorConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = [
            'id', 'name', 'is_active', 'interface', 'config',
            'parser_type', 'parser_config', 'read_interval'
        ]

class DeviceConfigSerializer(serializers.ModelSerializer):
    sensors = SensorConfigSerializer(many=True, read_only=True)
    class Meta:
        model = Device
        fields = ['id', 'name', 'location', 'sensors']

# --- Veri Gönderimi için Serializer ---
# Agent'ın sensör verisi göndermesi için kullanılır.
class SensorReadingSerializer(serializers.ModelSerializer):
    sensor = serializers.PrimaryKeyRelatedField(queryset=Sensor.objects.all())
    class Meta:
        model = SensorReading
        fields = ['sensor', 'value', 'timestamp']
        read_only_fields = ['timestamp']

# --- CRUD (Oluşturma/Okuma/Güncelleme/Silme) İşlemleri için Serializer'lar ---

# Bu küçük serializer, DeviceSerializer tarafından kullanılır.
class SimpleReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensorReading
        fields = ['value', 'timestamp']

# Arayüzdeki İstasyon (Device) yönetimi için kullanılır.
class DeviceSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()
    last_reading = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = [
            'id', 'name', 'location', 'latitude', 'longitude', 
            'is_active', 'user', 'last_reading'
        ]
        read_only_fields = ['id', 'user', 'last_reading']

    def get_last_reading(self, obj):
        """Cihaza ait en son sensör okumasını bulur ve serileştirir."""
        last_reading = SensorReading.objects.filter(sensor__device=obj).order_by('-timestamp').first()
        if last_reading:
            return SimpleReadingSerializer(last_reading).data
        return None

# Arayüzdeki Sensör yönetimi için kullanılır.
class SensorSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all())
    class Meta:
        model = Sensor
        fields = [
            'id', 'name', 'device', 'device_name', 'is_active', 'interface', 
            'config', 'parser_type', 'parser_config', 'read_interval'
        ]
        read_only_fields = ['id', 'device_name']

class AnalyticsDataSerializer(serializers.ModelSerializer):
    """ Veri analizi grafiği için SensorReading verisini serileştirir. """
    class Meta:
        model = SensorReading
        fields = ['timestamp', 'value']