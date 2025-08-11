import configparser
import json
import os
import re
import sqlite3
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler
import requests

# --- Donanım Kütüphaneleri ---
try:
    import serial
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False
try:
    from smbus2 import SMBus, i2c_msg
    SMBUS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    SMBUS_AVAILABLE = False

class OrionAgent:
    def __init__(self, config_file='config.ini'):
        print("--- Orion Agent Başlatılıyor ---")
        self.is_configured = False
        local_config = self._load_ini_config(config_file)
        if not local_config: return
        self.base_url = local_config['server']['base_url']
        self.token = local_config['device']['token']
        self.headers = {'Authorization': f'Token {self.token}', 'Content-Type': 'application/json'}
        self.db_path = os.path.join(os.path.dirname(__file__), 'offline_queue.db')
        if not self._init_local_db(): return
        self.device_config = None
        self.scheduler = BlockingScheduler(timezone="Europe/Istanbul")
        self.reading_cache = {}
        self.is_configured = True
        print("✅ Agent başlatılmaya hazır.")

    def _load_ini_config(self, config_file):
        print(f"Yerel konfigürasyon okunuyor: {config_file}")
        try:
            parser = configparser.ConfigParser()
            if not parser.read(config_file, encoding='utf-8'): raise FileNotFoundError(f"{config_file} bulunamadı veya boş.")
            return {s: dict(parser.items(s)) for s in parser.sections()}
        except Exception as e:
            print(f"❌ HATA: Yerel konfigürasyon okunamadı! {e}"); return None

    def _init_local_db(self):
        print("Yerel çevrimdışı kuyruk veritabanı kontrol ediliyor...")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('CREATE TABLE IF NOT EXISTS readings (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)')
            conn.commit(); conn.close()
            print("✅ Veritabanı hazır."); return True
        except Exception as e:
            print(f"❌ HATA: Yerel veritabanı oluşturulamadı: {e}"); return False

    def get_server_configuration(self):
        print("\n📡 Sunucudan cihaz yapılandırması isteniyor...")
        try:
            response = requests.get(f"{self.base_url}/api/v3/device/config/", headers=self.headers, timeout=10)
            if response.status_code == 200:
                self.device_config = response.json()
                print("✅ Yapılandırma başarıyla alındı."); return True
            else:
                print(f"❌ HATA: Yapılandırma alınamadı. Sunucu: {response.status_code}"); return False
        except requests.exceptions.RequestException as e:
            print(f"❌ HATA: Sunucuya bağlanılamadı! {e}"); return False

    def master_read_cycle(self):
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n🔄 ({ts}) Ana okuma döngüsü başladı.")
        self._process_offline_queue()
        print("--- Fiziksel Sensörler Okunuyor ---")
        self.reading_cache.clear()
        self._read_all_physical_sensors()
        print("--- Okuma Tamamlandı ---")
        if not self.reading_cache:
            print("-> Gönderilecek yeni veri bulunamadı.")
            return
        print("\n--- Yeni Veriler Sunucuya Gönderiliyor ---")
        for sensor_id, value in self.reading_cache.items():
            payload = {"sensor": sensor_id, "value": value}
            print(f"   -> {json.dumps(payload)}")
            success, message = self._send_data_to_server(payload)
            if success: print(f"   -> ✅ Başarılı.")
            else:
                print(f"   -> ❌ Başarısız: {message}. Veri kuyruğa alınıyor.")
                self._queue_data_locally(payload)
        print("--- Gönderim Tamamlandı ---")

    def _read_all_physical_sensors(self):
        sensors = [s for s in self.device_config.get('sensors', []) if s.get('is_active') and s.get('interface') != 'virtual']
        for config in sensors:
            interface = config.get('interface')
            print(f"  -> Okunuyor: {config['name']} ({interface})")
            raw_data = None
            if interface == 'serial':
                raw_data = self._read_serial(config) # Artık tüm sensör konfigürasyonunu gönderiyoruz
            elif interface == 'i2c':
                raw_data = self._read_i2c(config.get('config', {}))
            
            if raw_data is None: print("     -> Ham veri okunamadı."); continue
            
            parsed_data = self._parse_data(raw_data, config)
            if parsed_data is None: print("     -> Veri ayrıştırılamadı."); continue
            
            print(f"     -> İşlenmiş Veri: {parsed_data}")
            self.reading_cache[config['id']] = parsed_data

    # GÜNCELLENDİ: Bu fonksiyon artık daha akıllı
    def _read_serial(self, sensor_config):
        if not PYSERIAL_AVAILABLE: return None
        
        config = sensor_config.get('config', {})
        parser_config = sensor_config.get('parser_config', {})
        port = config.get('port')
        if not port: return None
        
        try:
            with serial.Serial(port, config.get('baudrate', 9600), timeout=2) as ser:
                ser.reset_input_buffer()
                time.sleep(0.1) # Kısa bir bekleme
                
                # Konfigürasyona göre özel okuma mantığı
                bytes_to_read = parser_config.get('read_bytes')
                if bytes_to_read:
                    # DFRobot Lidar gibi belirli sayıda byte bekleyen sensörler için
                    start_time = time.time()
                    while ser.in_waiting < bytes_to_read:
                        if time.time() - start_time > 2: # 2 saniye timeout
                            print(f"     -> Zaman aşımı: {bytes_to_read} byte veri alınamadı.")
                            return None
                    return ser.read(bytes_to_read)
                else:
                    # Ağırlık sensörü gibi metin tabanlı sensörler için
                    return ser.readline()

        except serial.SerialException as e:
            print(f"     -> HATA: Seri port açılamadı ({port}): {e}")
            return None

    def _read_i2c(self, config):
        if not SMBUS_AVAILABLE: return None
        addr = config.get('address'); bus_n = config.get('bus', 1)
        if not addr: return None
        try:
            i2c_addr = int(str(addr), 16)
            with SMBus(bus_n) as bus:
                write = i2c_msg.write(i2c_addr, [0x2C, 0x06]); read = i2c_msg.read(i2c_addr, 6)
                bus.i2c_rdwr(write); time.sleep(0.5); bus.i2c_rdwr(read)
                data = list(read)
                temp = -45 + (175 * (data[0] * 256 + data[1])) / 65535.0
                hum = 100 * (data[3] * 256 + data[4]) / 65535.0
                return {'temperature': round(temp, 2), 'humidity': round(hum, 2)}
        except (OSError, ValueError) as e:
            print(f"     -> HATA: I2C sensöründen okunamadı ({addr}): {e}"); return None

    def _parse_data(self, raw_data, sensor_config):
        parser_type = sensor_config.get('parser_type')
        parser_config = sensor_config.get('parser_config', {})
        
        if parser_type == 'regex':
            rule = parser_config.get('rule')
            if not rule: return None
            text_data = raw_data.decode('utf-8', errors='ignore').strip()
            match = re.search(rule, text_data)
            if match:
                if match.groupdict():
                    return {k: float(v) for k, v in match.groupdict().items()}
                else:
                    return {'value': float(match.group(1))}
            return None
        
        elif parser_type == 'binary':
            binary_format = parser_config.get('format')
            if not binary_format:
                print("     -> HATA: Binary parser için 'format' belirtilmemiş."); return None
            if binary_format == 'dfrobot_lidar':
                return self._parse_binary_dfrobot_lidar(raw_data)
            else:
                print(f"     -> UYARI: Bilinmeyen binary formatı: {binary_format}"); return None
        
        elif parser_type == 'simple': return raw_data
        print(f"     -> UYARI: Bilinmeyen ayrıştırıcı tipi: {parser_type}"); return None

    def _parse_binary_dfrobot_lidar(self, packet):
        if not isinstance(packet, bytes) or len(packet) != 4: return None
        if packet[0] != 0xFF: print("     -> Başlık baytı geçersiz!"); return None
        checksum = (packet[0] + packet[1] + packet[2]) & 0xFF
        if checksum != packet[3]: print("     -> Checksum hatası!"); return None
        distance_mm = (packet[1] << 8) + packet[2]
        return {'distance_cm': round(distance_mm / 10.0, 1)}

    def _send_data_to_server(self, payload):
        try:
            r = requests.post(f"{self.base_url}/api/v3/readings/submit/", headers=self.headers, json=payload, timeout=10)
            return (True, "OK") if r.status_code == 201 else (False, f"Sunucu Hatası {r.status_code}")
        except requests.exceptions.RequestException as e: return False, "Bağlantı Hatası"

    def _queue_data_locally(self, payload):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.cursor().execute("INSERT INTO readings (payload) VALUES (?)", (json.dumps(payload),))
            conn.commit(); conn.close()
        except Exception as e: print(f"   -> ❌ HATA: Veri yerel kuyruğa eklenemedi: {e}")

    def _process_offline_queue(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            items = cursor.execute("SELECT id, payload FROM readings ORDER BY id ASC").fetchall()
            if items:
                print(f"\n📬 Çevrimdışı kuyrukta {len(items)} kayıt var, gönderiliyor...")
                for item in items:
                    success, msg = self._send_data_to_server(json.loads(item['payload']))
                    if success:
                        print(f"   -> Kuyruk (ID: {item['id']}) gönderildi.")
                        cursor.execute("DELETE FROM readings WHERE id = ?", (item['id'],))
                        conn.commit()
                    else:
                        print("   -> Sunucuya ulaşılamıyor, kuyruk işlemi durduruldu."); break
            conn.close()
        except Exception as e: print(f"   -> ❌ HATA: Kuyruk işlenemedi: {e}")

    def run(self):
        if not self.is_configured: sys.exit("❌ Agent, yerel konfigürasyon hatası nedeniyle başlatılamıyor.")
        if not self.get_server_configuration(): sys.exit("❌ Agent, sunucuya bağlanamadığı için başlatılamıyor.")
        run_interval = 10
        print(f"\n⏰ Zamanlayıcı kuruldu. Ana döngü her {run_interval} saniyede bir çalışacak.")
        print("💡 Çıkmak için Ctrl+C'ye basın.")
        try:
            self.master_read_cycle()
            self.scheduler.add_job(self.master_read_cycle, 'interval', seconds=run_interval)
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\n🛑 Agent durduruluyor..."); self.scheduler.shutdown()

if __name__ == "__main__":
    agent = OrionAgent()
    agent.run()