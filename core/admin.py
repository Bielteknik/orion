from django.contrib import admin
from rest_framework.authtoken.models import Token
from .models import (
    Device, 
    Sensor, 
    SensorReading, 
    Rule, 
    Condition, 
    Action, 
    NotificationRecipient
)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'get_token', 'location', 'is_active', 'last_seen')
    readonly_fields = ('id', 'last_seen', 'health_status', 'get_token')
    
    def get_token(self, obj):
        token, created = Token.objects.get_or_create(user=obj.user)
        return token.key
    get_token.short_description = 'Cihaz Tokenı'

@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ('name', 'device', 'is_active', 'interface', 'read_interval')
    list_filter = ('device', 'is_active', 'interface')
    search_fields = ('name', 'device__name')

# Sadece admin panelinde görünsün diye SensorReading'i de kaydedelim.
@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ('sensor', 'timestamp', 'value')
    list_filter = ('sensor__device', 'sensor', 'timestamp')
    readonly_fields = ('sensor', 'value', 'timestamp')

# --- YENİ EKLENEN VE DÜZELTİLEN KISIM ---

@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(admin.ModelAdmin):
    list_display = ('name', 'recipient_type', 'address', 'is_active')
    list_filter = ('recipient_type', 'is_active')

class ConditionInline(admin.TabularInline):
    model = Condition
    extra = 1

class ActionInline(admin.TabularInline):
    model = Action
    extra = 1
    # Bu özellik, ManyToMany alanını daha kullanıcı dostu bir seçme kutusu yapar.
    filter_horizontal = ('recipients',)

@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'trigger_sensor', 'is_active', 'description')
    list_filter = ('is_active', 'trigger_sensor__device')
    inlines = [ConditionInline, ActionInline]