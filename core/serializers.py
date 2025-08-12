# core/serializers.py DOSYASININ NİHAİ, TAM ve DOĞRU HALİ
from rest_framework import serializers
from .models import Device, Sensor, SensorReading, Rule, Condition, Action, Camera, Command, CameraCapture

class SensorConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = ['id', 'name', 'is_active', 'interface', 'config', 'parser_type', 'parser_config', 'read_interval']

class DeviceConfigSerializer(serializers.ModelSerializer):
    sensors = SensorConfigSerializer(many=True, read_only=True)
    class Meta:
        model = Device; fields = ['id', 'name', 'location', 'sensors']

class SensorReadingSerializer(serializers.ModelSerializer):
    sensor = serializers.PrimaryKeyRelatedField(queryset=Sensor.objects.all())
    class Meta:
        model = SensorReading; fields = ['sensor', 'value', 'timestamp']; read_only_fields = ['timestamp']

class SimpleReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensorReading; fields = ['value', 'timestamp']

class DeviceSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(); last_reading = serializers.SerializerMethodField()
    class Meta:
        model = Device
        fields = ['id', 'name', 'location', 'latitude', 'longitude', 'is_active', 'user', 'last_reading']
        read_only_fields = ['id', 'user', 'last_reading']
    def get_last_reading(self, obj):
        lr = SensorReading.objects.filter(sensor__device=obj).order_by('-timestamp').first()
        if lr: return SimpleReadingSerializer(lr).data
        return None

class SensorSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    device = serializers.PrimaryKeyRelatedField(queryset=Device.objects.all())
    class Meta:
        model = Sensor
        fields = ['id', 'name', 'device', 'device_name', 'is_active', 'interface', 'config', 'parser_type', 'parser_config', 'read_interval']
        read_only_fields = ['id', 'device_name']

class ConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condition; fields = ['id', 'variable_key', 'operator', 'comparison_value']

class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action; fields = ['id', 'action_type', 'recipients', 'config']

class RuleSerializer(serializers.ModelSerializer):
    conditions = ConditionSerializer(many=True); actions = ActionSerializer(many=True)
    class Meta:
        model = Rule; fields = ['id', 'name', 'description', 'trigger_sensor', 'is_active', 'cooldown_minutes', 'conditions', 'actions']
    def create(self, vd):
        conds = vd.pop('conditions'); acts = vd.pop('actions'); rule = Rule.objects.create(**vd)
        for c in conds: Condition.objects.create(rule=rule, **c)
        for a in acts:
            recps = a.pop('recipients', []); act = Action.objects.create(rule=rule, **a); act.recipients.set(recps)
        return rule

class CameraSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    class Meta:
        model = Camera; fields = '__all__'

class CommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command; fields = '__all__'

class CameraCaptureSerializer(serializers.ModelSerializer):
    class Meta:
        model = CameraCapture; fields = '__all__'