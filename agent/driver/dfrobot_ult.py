import serial
import time

def read(config):
    """
    DFRobot Lidar sensöründen 4-byte'lık binary veriyi okur.
    'config' sözlüğü, {'port': '/dev/ttyMESAFE', 'baudrate': 9600} gibi ayarları içerir.
    """
    port = config.get('port')
    if not port:
        print("     -> HATA (Lidar): Port belirtilmemiş.")
        return None

    try:
        with serial.Serial(port, config.get('baudrate', 9600), timeout=2) as ser:
            ser.reset_input_buffer()
            
            start_time = time.time()
            # Doğru paketi bulmak için biraz daha fazla veri oku
            buffer = b''
            while time.time() - start_time < 2:
                buffer += ser.read(ser.in_waiting or 1)
                start_index = buffer.find(b'\xFF')
                
                if start_index != -1 and len(buffer) >= start_index + 4:
                    packet = buffer[start_index : start_index + 4]
                    checksum = (packet[0] + packet[1] + packet[2]) & 0xFF
                    if checksum == packet[3]:
                        distance_mm = (packet[1] << 8) + packet[2]
                        return {'distance_cm': round(distance_mm / 10.0, 1)}
            
            print("     -> UYARI (Lidar): Zaman aşımı, geçerli Lidar paketi bulunamadı.")
            return None

    except serial.SerialException as e:
        print(f"     -> HATA (Lidar): Seri port açılamadı ({port}): {e}")
        return None