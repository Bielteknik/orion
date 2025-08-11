from rest_framework import serializers
from .models import Device, Sensor, SensorReading

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

class DeviceConfigSerializer(serializers.ModelSerializer):
    # Bu sensörler, Device modelindeki 'sensors' related_name'inden gelir.
    sensors = SensorSerializer(many=True, read_only=True)
    
    class Meta:
        model = Device
        fields = ['id', 'name', 'location', 'sensors']

class SensorReadingSerializer(serializers.ModelSerializer):
    """
    İstemciden gelen sensör okumalarını doğrulamak ve kaydetmek için kullanılır.
    İstemci sadece 'sensor' ID'sini ve 'value' JSON'ını gönderecek.
    """
    # Agent'tan gelen veride 'sensor' alanı, bir sensörün ID'si olacak.
    # PrimaryKeyRelatedField, bu ID'nin geçerli bir Sensor olup olmadığını kontrol eder.
    sensor = serializers.PrimaryKeyRelatedField(queryset=Sensor.objects.all())

    class Meta:
        model = SensorReading
        fields = ['sensor', 'value', 'timestamp']
        # timestamp alanı sunucu tarafından otomatik oluşturulacağı için sadece okunabilir.
        read_only_fields = ['timestamp']

class DeviceSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()
    
    class Meta:
        model = Device
        # Yeni alanları ekle
        fields = ['id', 'name', 'location', 'latitude', 'longitude', 'is_active', 'user']
        read_only_fields = ['id', 'user']