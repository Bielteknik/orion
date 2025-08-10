from rest_framework import serializers
from .models import Device, Sensor

class SensorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = [
            'id', 'name', 'is_active', 'interface', 'config',
            'parser_type', 'parser_config', 'read_interval'
        ]

class DeviceConfigSerializer(serializers.ModelSerializer):
    # Bu sensörler, Device modelindeki 'sensors' related_name'inden gelir.
    sensors = SensorSerializer(many=True, read_only=True)
    
    class Meta:
        model = Device
        fields = ['id', 'name', 'location', 'sensors']