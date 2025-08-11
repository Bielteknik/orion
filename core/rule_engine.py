import operator
from django.conf import settings
from django.core.mail import send_mail
from .models import Alert, Rule
from django.utils import timezone
from datetime import timedelta

# Python'daki karşılaştırma operatörlerini bir sözlükte tutalım
OPS = {
    '>': operator.gt, '>=': operator.ge,
    '<': operator.lt, '<=': operator.le,
    '==': operator.eq, '!=': operator.ne,
}

def execute_actions_for_rule(rule, context):
    """
    Bir kural için tanımlanmış tüm eylemleri çalıştırır ve bir Alert kaydı oluşturur.
    """
    
    # 1. Alert (Uyarı) kaydını veritabanına oluştur
    # Bu mesaj, hem Alert kaydında hem de e-postada kullanılabilir.
    alert_message = (
        f"{context.get('device_name', 'Bilinmeyen Cihaz')} cihazındaki "
        f"{context.get('sensor_name', 'Bilinmeyen Sensör')} sensöründe kural tetiklendi. "
        f"Gelen Değerler: {context}"
    )

    try:
        Alert.objects.create(
            rule=rule,
            device=rule.trigger_sensor.device,
            message=alert_message,
            # Kuralın adına bakarak önem derecesini belirleyebiliriz.
            # Örneğin, kural adı "Kritik" içeriyorsa, önem derecesi de kritik olur.
            severity='critical' if 'kritik' in rule.name.lower() else 'warning'
        )
        print(f"  -> BİLGİ: Veritabanına uyarı kaydı oluşturuldu.")
    except Exception as e:
        print(f"  -> HATA: Uyarı kaydı oluşturulamadı: {e}")


    # 2. Tanımlanmış eylemleri (e-posta vb.) çalıştır
    for action in rule.actions.all():
        if action.action_type == 'log_to_console':
            message_template = action.config.get('message', 'Eylem tetiklendi!')
            message = message_template.format(**context)
            print(f"  -> EYLEM (Konsol): {message}")

        elif action.action_type == 'send_email':
            print(f"  -> EYLEM (E-posta): Tetikleniyor...")
            
            # Mesaj şablonunu al ve dinamik verilerle doldur
            subject_template = action.config.get('subject', 'SNOW IOT Uyarısı: {rule_name}')
            body_template = action.config.get('body', 'Cihaz: {device_name}\nSensör: {sensor_name}\n\nDetaylar:\n{value_details}')
            
            # Gelen tüm verileri daha okunaklı bir string'e çevirelim
            value_details_str = "\n".join([f"- {key.capitalize()}: {value}" for key, value in context.items() if key not in ['rule_name', 'sensor_name', 'device_name']])
            context['value_details'] = value_details_str

            subject = subject_template.format(**context)
            body = body_template.format(**context)

            # Eyleme atanmış ve aktif olan tüm alıcıların e-posta adreslerini al
            recipient_list = [
                recipient.address for recipient in action.recipients.filter(is_active=True, recipient_type='email')
            ]

            if not recipient_list:
                print("     -> UYARI: E-posta eylemi için aktif alıcı bulunamadı.")
                continue

            try:
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                print(f"     -> Başarılı: E-posta {', '.join(recipient_list)} adres(ler)ine gönderildi.")
            except Exception as e:
                print(f"     -> ❌ HATA: E-posta gönderilemedi: {e}")


def process_rules_for_reading(reading_instance):
    """
    Verilen bir sensör okuması için ilgili tüm kuralları kontrol eder ve eylemleri tetikler.
    Artık "cooldown" (susturma) mekanizması içerir.
    """
    sensor = reading_instance.sensor
    rules_to_check = Rule.objects.filter(
        trigger_sensor=sensor, 
        is_active=True
    ).prefetch_related('conditions', 'actions__recipients')

    if not rules_to_check.exists():
        return

    print(f"--- Kural Motoru: {sensor.name} sensöründen gelen veri için {rules_to_check.count()} kural kontrol ediliyor ---")

    for rule in rules_to_check:
        # --- YENİ: COOLDOWN KONTROLÜ ---
        if rule.last_triggered:
            # Kuralın tekrar tetiklenebilmesi için geçmesi gereken zaman
            cooldown_period = timedelta(minutes=rule.cooldown_minutes)
            # Ne zaman tekrar aktif olacağı
            next_trigger_time = rule.last_triggered + cooldown_period
            
            # Eğer hala susturma periyodu içindeysek, bu kuralı atla
            if timezone.now() < next_trigger_time:
                print(f"ℹ️  KURAL SUSTURULDU: '{rule.name}' kuralı {next_trigger_time.strftime('%H:%M')} saatine kadar tekrar tetiklenmeyecek.")
                continue # Bir sonraki kurala geç
        # --- KONTROL BİTTİ ---

        all_conditions_met = True
        for condition in rule.conditions.all():
            # ... (koşul kontrol mantığı aynı kalıyor) ...
            variable_key = condition.variable_key
            if variable_key not in reading_instance.value:
                all_conditions_met = False; break
            try:
                current_value = float(reading_instance.value[variable_key])
                comparison_value = float(condition.comparison_value)
                op_func = OPS.get(condition.operator)
                if not op_func or not op_func(current_value, comparison_value):
                    all_conditions_met = False; break
            except (ValueError, TypeError):
                 all_conditions_met = False; break

        if all_conditions_met:
            print(f"✅ KURAL TETİKLENDİ: '{rule.name}'")
            
            # YENİ: Kural tetiklendiği anda, son tetiklenme zamanını güncelle
            rule.last_triggered = timezone.now()
            rule.save(update_fields=['last_triggered'])

            context = {
                'rule_name': rule.name,
                'sensor_name': sensor.name,
                'device_name': sensor.device.name,
            }
            if isinstance(reading_instance.value, dict):
                context.update(reading_instance.value)
            
            execute_actions_for_rule(rule, context)

