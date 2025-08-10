from django.db import models
from django.contrib.auth.models import User
import uuid

class Device(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Cihaz Sahibi")
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True, verbose_name="Cihaz Adı")
    location = models.CharField(max_length=200, blank=True, verbose_name="Konum")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    last_seen = models.DateTimeField(null=True, blank=True, verbose_name="Son Görülme")
    health_status = models.JSONField(null=True, blank=True, default=dict, verbose_name="Sağlık Durumu")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Cihaz"
        verbose_name_plural = "Cihazlar"

class Sensor(models.Model):
    INTERFACE_CHOICES = [('serial', 'Seri Port'), ('i2c', 'I2C'), ('virtual', 'Sanal')]
    PARSER_TYPE_CHOICES = [('regex', 'Regex'), ('binary', 'Binary'), ('simple', 'Basit')]

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='sensors', verbose_name="Bağlı Olduğu Cihaz")
    name = models.CharField(max_length=100, verbose_name="Sensör Adı")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    
    interface = models.CharField(max_length=20, choices=INTERFACE_CHOICES, verbose_name="Arayüz Tipi")
    config = models.JSONField(default=dict, blank=True, verbose_name="Arayüz Yapılandırması (JSON)")
    
    parser_type = models.CharField(max_length=20, choices=PARSER_TYPE_CHOICES, verbose_name="Veri Ayrıştırıcı Tipi")
    parser_config = models.JSONField(default=dict, blank=True, verbose_name="Ayrıştırıcı Yapılandırması (JSON)")

    read_interval = models.PositiveIntegerField(default=60, verbose_name="Okuma Sıklığı (Saniye)")

    def __str__(self):
        return f"{self.device.name} - {self.name}"

    class Meta:
        verbose_name = "Sensör"
        verbose_name_plural = "Sensörler"
        unique_together = ('device', 'name')

class SensorReading(models.Model):
    """
    Bir sensörden gelen her bir ölçümü saklar.
    """
    # on_delete=models.CASCADE: Sensör silinirse, ona ait okumalar da silinir.
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, related_name='readings', verbose_name="Sensör")
    
    # Okunan veriyi esnek bir şekilde saklamak için JSONField kullanıyoruz.
    # Örn: {"temperature": 25.4, "humidity": 60.1}
    value = models.JSONField(verbose_name="Ölçüm Değeri")

    # Okumanın ne zaman yapıldığını gösteren zaman damgası.
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Zaman Damgası")

    def __str__(self):
        return f"{self.sensor.name} @ {self.timestamp.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        verbose_name = "Sensör Okuması"
        verbose_name_plural = "Sensör Okumaları"
        ordering = ['-timestamp'] # Okumaları en yeniden en eskiye sırala