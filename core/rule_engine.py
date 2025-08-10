import operator
from django.core.mail import send_mail
from .models import Rule

# Python'daki karşılaştırma operatörlerini bir sözlükte tutalım
OPS = {
    '>': operator.gt, '>=': operator.ge,
    '<': operator.lt, '<=': operator.le,
    '==': operator.eq, '!=': operator.ne,
}

def execute_actions_for_rule(rule, context):
    """
    Bir kural için tanımlanmış tüm eylemleri çalıştırır.
    Bu fonksiyon artık 2 argüman alıyor: 'rule' ve 'context'.
    """
    for action in rule.actions.all():
        if action.action_type == 'log_to_console':
            message_template = action.config.get('message', 'Eylem tetiklendi!')
            message = message_template.format(**context)
            print(f"  -> EYLEM (Konsol): {message}")

        elif action.action_type == 'send_email':
            print(f"  -> EYLEM (E-posta): Tetikleniyor...")
            
            subject_template = action.config.get('subject', 'SNOW IOT Uyarısı: {rule_name}')
            body_template = action.config.get('body', 'Cihaz: {device_name}\nSensör: {sensor_name}\nSıcaklık: {temperature}\nNem: {humidity}')
            
            subject = subject_template.format(**context)
            body = body_template.format(**context)

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
                    from_email='noreply@snowiot.com',
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                print(f"     -> Başarılı: E-posta {', '.join(recipient_list)} adres(ler)ine gönderildi (konsola yazdırıldı).")
            except Exception as e:
                print(f"     -> ❌ HATA: E-posta gönderilemedi: {e}")

def process_rules_for_reading(reading_instance):
    """
    Verilen bir sensör okuması için ilgili tüm kuralları kontrol eder ve eylemleri tetikler.
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
        all_conditions_met = True
        for condition in rule.conditions.all():
            variable_key = condition.variable_key
            if variable_key not in reading_instance.value:
                all_conditions_met = False
                break
            
            try:
                current_value = float(reading_instance.value[variable_key])
                comparison_value = float(condition.comparison_value)
                op_func = OPS.get(condition.operator)
                if not op_func or not op_func(current_value, comparison_value):
                    all_conditions_met = False
                    break
            except (ValueError, TypeError):
                 print(f"UYARI: Kural '{rule.name}', koşul '{condition}' sayısal olmayan değerler içeriyor, atlanıyor.")
                 all_conditions_met = False
                 break

        if all_conditions_met:
            print(f"✅ KURAL TETİKLENDİ: '{rule.name}'")
            
            context = {
                'rule_name': rule.name,
                'sensor_name': sensor.name,
                'device_name': sensor.device.name,
            }
            if isinstance(reading_instance.value, dict):
                context.update(reading_instance.value)
            
            # Çağrı yapılan yerdeki argüman sayısı ile fonksiyon tanımındaki argüman sayısı artık eşleşiyor.
            execute_actions_for_rule(rule, context)