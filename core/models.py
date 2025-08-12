from django.db import models
from django.contrib.auth.models import User
import uuid

class Device(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Cihaz Sahibi")
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True, verbose_name="Cihaz Adı")

    # YENİ ALANLAR
    location = models.CharField(max_length=200, blank=True, verbose_name="Konum")    
    latitude = models.FloatField(null=True, blank=True, verbose_name="Enlem")
    longitude = models.FloatField(null=True, blank=True, verbose_name="Boylam")

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
    PARSER_TYPE_CHOICES = [('regex', 'Regex'), ('binary', 'Binary Format'), ('simple', 'Basit (Değerin kendisi)')]

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='sensors', verbose_name="Bağlı Olduğu Cihaz")
    name = models.CharField(max_length=100, verbose_name="Sensör Adı")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    
    interface = models.CharField(
        max_length=20, 
        choices=INTERFACE_CHOICES, 
        verbose_name="Arayüz Tipi",
        blank=True # Artık bu alan boş olabilir
    )
    config = models.JSONField(default=dict, blank=True, verbose_name="Arayüz Yapılandırması (JSON)")
    
    parser_type = models.CharField(
        max_length=20, 
        choices=PARSER_TYPE_CHOICES, 
        verbose_name="Veri Ayrıştırıcı Tipi",
        blank=True # Artık bu alan boş olabilir
    )
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

class Rule(models.Model):
    """
    Bir veya daha fazla koşul ve eylemden oluşan bir kural setini tanımlar.
    Örn: "Aşırı Sıcaklık Uyarısı"
    """
    name = models.CharField(max_length=200, unique=True, verbose_name="Kural Adı")
    description = models.TextField(blank=True, verbose_name="Açıklama")
    # Bu kural, hangi sensörden veri geldiğinde kontrol edilmeli?
    trigger_sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, verbose_name="Tetikleyici Sensör")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    # YENİ ALANLAR
    last_triggered = models.DateTimeField(null=True, blank=True, verbose_name="Son Tetiklenme Zamanı")
    cooldown_minutes = models.PositiveIntegerField(default=60, verbose_name="Tekrar Bildirme Sıklığı (Dakika)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Kural"
        verbose_name_plural = "Kurallar"

class Condition(models.Model):
    """
    Bir kuralın içindeki tek bir 'EĞER' koşulunu tanımlar.
    Örn: "EĞER sıcaklık > 20"
    """
    OPERATOR_CHOICES = [
        ('>', 'Büyüktür'),
        ('>=', 'Büyük veya Eşittir'),
        ('<', 'Küçüktür'),
        ('<=', 'Küçük veya Eşittir'),
        ('==', 'Eşittir'),
        ('!=', 'Eşit Değildir'),
    ]
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name='conditions', verbose_name="Ait Olduğu Kural")
    # Gelen JSON veri içindeki hangi anahtarı kontrol edeceğiz? Örn: "temperature"
    variable_key = models.CharField(max_length=100, verbose_name="Değişken Anahtarı (JSON Key)")
    operator = models.CharField(max_length=4, choices=OPERATOR_CHOICES, verbose_name="Operatör")
    # Ne ile karşılaştıracağız? Örn: 20
    comparison_value = models.CharField(max_length=100, verbose_name="Karşılaştırma Değeri")

    def __str__(self):
        return f"EĞER {self.variable_key} {self.get_operator_display()} {self.comparison_value}"

    class Meta:
        verbose_name = "Koşul"
        verbose_name_plural = "Koşullar"

class NotificationRecipient(models.Model):
    """Bildirimlerin gönderileceği kişileri veya hedefleri tanımlar."""
    RECIPIENT_TYPE_CHOICES = [
        ('email', 'E-posta'),
        # ('sms', 'SMS'), -- Gelecek için
    ]
    name = models.CharField(max_length=100, verbose_name="Alıcı Adı (örn: Proje Sorumlusu)")
    recipient_type = models.CharField(max_length=10, choices=RECIPIENT_TYPE_CHOICES, verbose_name="Alıcı Tipi")
    address = models.CharField(max_length=255, verbose_name="Adres (e-posta, telefon no, vb.)")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")

    def __str__(self):
        return f"{self.name} ({self.address})"

    class Meta:
        verbose_name = "Bildirim Alıcısı"
        verbose_name_plural = "Bildirim Alıcıları"

class Alert(models.Model):
    """
    Kural motoru tarafından tetiklenen her bir uyarıyı kaydeder.
    """
    SEVERITY_CHOICES = [
        ('info', 'Bilgi'),
        ('warning', 'Uyarı'),
        ('critical', 'Kritik'),
    ]
    
    # Hangi kuralın bu uyarıyı tetiklediği
    rule = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True, verbose_name="Tetikleyen Kural")
    # Uyarının ne zaman oluştuğu
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    # Uyarının içeriği
    message = models.TextField(verbose_name="Uyarı Mesajı")
    # Görüldü/Çözüldü olarak işaretlendi mi?
    is_acknowledged = models.BooleanField(default=False, verbose_name="Görüldü mü?")
    # Uyarının önemi
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='warning', verbose_name="Önem Derecesi")
    
    # Hangi cihazla ilgili olduğu
    device = models.ForeignKey(Device, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.rule.name if self.rule else 'Bilinmeyen Kural'} @ {self.timestamp.strftime('%d.%m.%Y %H:%M')}"

    class Meta:
        verbose_name = "Uyarı"
        verbose_name_plural = "Uyarılar"
        ordering = ['-timestamp']

class Action(models.Model):
    """
    Bir kuralın koşulları sağlandığında çalıştırılacak eylemi tanımlar.
    """
    ACTION_TYPE_CHOICES = [
        ('log_to_console', 'Sunucu Konsoluna Yaz'),
        ('send_email', 'E-posta Gönder'), # YENİ EYLEM TİPİ
    ]
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name='actions', verbose_name="Ait Olduğu Kural")
    action_type = models.CharField(max_length=20, choices=ACTION_TYPE_CHOICES, verbose_name="Eylem Tipi")
    
    # YENİ: E-posta gönderilecek alıcıları seçmek için.
    # ManyToManyField, bir eylemin birden çok alıcısı olabileceğini belirtir.
    recipients = models.ManyToManyField(
        NotificationRecipient, 
        blank=True, # Bir eylemin alıcısı olmak zorunda değil (örn: log_to_console)
        verbose_name="Bildirim Alıcıları"
    )

    # config alanı, mesaj şablonu gibi ek bilgileri tutmaya devam edecek.
    config = models.JSONField(default=dict, blank=True, verbose_name="Eylem Yapılandırması (JSON)")

    def __str__(self):
        return f"EYLEM: {self.get_action_type_display()}"

    class Meta:
        verbose_name = "Eylem"
        verbose_name_plural = "Eylemler"

class Camera(models.Model):
    
    STATUS_CHOICES = [
        ('active', 'Aktif'),
        ('maintenance', 'Bakım'),
        ('offline', 'Offline'),
    ]

    name = models.CharField(max_length=100, verbose_name="Kamera Adı")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='cameras', verbose_name="Bağlı Olduğu İstasyon")
    rtsp_url = models.CharField(max_length=500, verbose_name="RTSP URL")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active', verbose_name="Durum")

    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    is_recording = models.BooleanField(default=False, verbose_name="Kayıt Yapıyor mu?")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.device.name} - {self.name}"

    class Meta:
        verbose_name = "Kamera"
        verbose_name_plural = "Kameralar"
        unique_together = ('device', 'name')

class CameraCapture(models.Model):
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name='captures')
    timestamp = models.DateTimeField(auto_now_add=True)
    # Fotoğraf dosyası media klasörüne kaydedilecek
    image = models.ImageField(upload_to='camera_captures/%Y/%m/%d/')
    
    class Meta:
        ordering = ['-timestamp']

class Command(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='commands')
    command_type = models.CharField(max_length=50) # örn: 'capture_photo'
    payload = models.JSONField(default=dict) # örn: {'camera_id': 1}
    is_executed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
