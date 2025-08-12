from argparse import Action
from threading import Condition
from rest_framework import serializers
from .models import Device, Rule, Sensor, SensorReading

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

class ConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condition
        fields = ['id', 'variable_key', 'operator', 'comparison_value']

class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action
        fields = ['id', 'action_type', 'recipients', 'config']

class RuleSerializer(serializers.ModelSerializer):
    # İç içe geçmiş verileri yönetmek için
    conditions = ConditionSerializer(many=True)
    actions = ActionSerializer(many=True)

    class Meta:
        model = Rule
        fields = [
            'id', 'name', 'description', 'trigger_sensor', 
            'is_active', 'cooldown_minutes', 'conditions', 'actions'
        ]

    def create(self, validated_data):
        conditions_data = validated_data.pop('conditions')
        actions_data = validated_data.pop('actions')
        rule = Rule.objects.create(**validated_data)
        for condition_data in conditions_data:
            Condition.objects.create(rule=rule, **condition_data)
        for action_data in actions_data:
            recipients = action_data.pop('recipients', [])
            action = Action.objects.create(rule=rule, **action_data)
            action.recipients.set(recipients)
        return rule

    def update(self, instance, validated_data):
        # Bu metod, düzenleme işlevi için daha sonra detaylandırılabilir.
        # Şimdilik temel güncelleme yeterli.
        instance.name = validated_data.get('name', instance.name)
        instance.description = validated_data.get('description', instance.description)
        # ... diğer alanlar ...
        instance.save()
        # Not: İç içe geçmiş koşul/eylem güncellemesi daha karmaşıktır.
        # Bu adımda şimdilik oluşturma ve listelemeye odaklanalım.
        return instance