import serial
import time
import re

def read(config):
    """
    HX711 tabanlı bir ağırlık sensöründen '=' ile başlayan metin verisini okur.
    'config' sözlüğü, {'port': '/dev/ttyAGIRLIK', 'baudrate': 9600} gibi ayarları içerir.
    """
    port = config.get('port')
    if not port:
        print("     -> HATA (HX711): Port belirtilmemiş.")
        return None

    try:
        with serial.Serial(port, config.get('baudrate', 9600), timeout=2) as ser:
            time.sleep(2) # Sensörün stabil hale gelmesi için bekle
            ser.reset_input_buffer()
            
            # Sensörden anlamlı bir veri gelene kadar birkaç satır oku
            for _ in range(5):
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith('='):
                    match = re.search(r'=\s*(-?\d+\.\d+)', line)
                    if match:
                        weight = float(match.group(1))
                        return {'weight_kg': weight} # Veriyi anlamlı bir anahtarla döndür
            
            print("     -> UYARI (HX711): 5 denemede geçerli veri bulunamadı.")
            return None

    except serial.SerialException as e:
        print(f"     -> HATA (HX711): Seri port açılamadı ({port}): {e}")
        return None