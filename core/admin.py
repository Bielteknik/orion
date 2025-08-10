from django.contrib import admin
from .models import Device, Sensor
from rest_framework.authtoken.models import Token

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