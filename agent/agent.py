import configparser
import json
import os
import re
import sqlite3
import sys
import time
import subprocess
from apscheduler.schedulers.blocking import BlockingScheduler
import requests

# --- Donanım Kütüphaneleri ---
try:
    import serial
    import serial.tools.list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False

try:
    from smbus2 import SMBus, i2c_msg
    SMBUS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    SMBUS_AVAILABLE = False

# --- Ana Agent Sınıfı ---
class OrionAgent:
    # ... (OrionAgent sınıfının tüm içeriği bir önceki cevaptakiyle BİREBİR AYNI) ...
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
            if not parser.read(config_file, encoding='utf-8'):
                raise FileNotFoundError(f"{config_file} bulunamadı veya boş.")
            return {s: dict(parser.items(s)) for s in parser.sections()}
        except Exception as e:
            print(f"❌ HATA: Yerel konfigürasyon okunamadı! {e}")
            return None

    def _init_local_db(self):
        print("Yerel çevrimdışı kuyruk veritabanı kontrol ediliyor...")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            conn.close()
            print("✅ Veritabanı hazır.")
            return True
        except Exception as e:
            print(f"❌ HATA: Yerel veritabanı oluşturulamadı: {e}")
            return False

    def get_server_configuration(self):
        print("\n📡 Sunucudan cihaz yapılandırması isteniyor...")
        config_url = f"{self.base_url}/api/v3/device/config/"
        try:
            response = requests.get(config_url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                self.device_config = response.json()
                print("✅ Yapılandırma başarıyla alındı.")
                return True
            else:
                print(f"❌ HATA: Yapılandırma alınamadı. Sunucu: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ HATA: Sunucuya bağlanılamadı! {e}")
            return False

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
            if success:
                print(f"   -> ✅ Başarılı.")
            else:
                print(f"   -> ❌ Başarısız: {message}. Veri kuyruğa alınıyor.")
                self._queue_data_locally(payload)
        print("--- Gönderim Tamamlandı ---")

    def _read_all_physical_sensors(self):
        sensors_to_read = [
            s for s in self.device_config.get('sensors', []) 
            if s.get('interface') != 'virtual' and s.get('is_active')
        ]
        for sensor_config in sensors_to_read:
            interface = sensor_config.get('interface')
            print(f"  -> Okunuyor: {sensor_config['name']} ({interface})")
            raw_data = None
            if interface == 'serial':
                raw_data = self._read_serial(sensor_config.get('config', {}))
            elif interface == 'i2c':
                raw_data = self._read_i2c(sensor_config.get('config', {}))
            else:
                print(f"     -> UYARI: Desteklenmeyen arayüz: {interface}")
                continue
            if raw_data is None:
                print("     -> Ham veri okunamadı.")
                continue
            parsed_data = self._parse_data(raw_data, sensor_config)
            if parsed_data is None:
                print("     -> Veri ayrıştırılamadı.")
                continue
            print(f"     -> İşlenmiş Veri: {parsed_data}")
            self.reading_cache[sensor_config['id']] = parsed_data

    def _read_serial(self, config):
        if not PYSERIAL_AVAILABLE: return None
        port = config.get('port')
        if not port: return None
        try:
            with serial.Serial(port, config.get('baudrate', 9600), timeout=2) as ser:
                time.sleep(1.8)
                return ser.read(100)
        except serial.SerialException as e:
            print(f"     -> HATA: Seri port açılamadı ({port}): {e}")
            return None

    def _read_i2c(self, config):
        if not SMBUS_AVAILABLE: return None
        address = config.get('address')
        if not address: return None
        try:
            i2c_addr = int(str(address), 16)
            with SMBus(config.get('bus', 1)) as bus:
                write = i2c_msg.write(i2c_addr, [0x2C, 0x06])
                read = i2c_msg.read(i2c_addr, 6)
                bus.i2c_rdwr(write)
                time.sleep(0.5)
                bus.i2c_rdwr(read)
                data = list(read)
                temp = -45 + (175 * (data[0] * 256 + data[1])) / 65535.0
                humidity = 100 * (data[3] * 256 + data[4]) / 65535.0
                return {'temperature': round(temp, 2), 'humidity': round(humidity, 2)}
        except (OSError, ValueError) as e:
            print(f"     -> HATA: I2C sensöründen okunamadı ({address}): {e}")
            return None

    def _parse_data(self, raw_data, sensor_config):
        parser_type = sensor_config.get('parser_type')
        parser_config = sensor_config.get('parser_config', {})

        if parser_type == 'regex':
            rule = parser_config.get('rule')
            if not rule: return None
            text_data = raw_data.decode('utf-8', errors='ignore')
            match = re.search(rule, text_data)
            if match:
                # İsimlendirilmiş grup varsa onu, yoksa ilk grubu kullan
                if match.groupdict():
                    # Değerleri float'a çevirmeyi dene, olmazsa string bırak
                    parsed = {}
                    for k, v in match.groupdict().items():
                        try:
                            parsed[k] = float(v)
                        except (ValueError, TypeError):
                            parsed[k] = v
                    return parsed
                else:
                    return {'value': float(match.group(1))}
            return None

        # --- YENİ ve GÜNCELLENMİŞ BINARY BLOK ---
        elif parser_type == 'binary':
            binary_format = parser_config.get('format')
            if not binary_format:
                print("     -> HATA: Binary parser için 'format' belirtilmemiş.")
                return None

            # Belirtilen formata göre ilgili işleyiciyi çağır
            if binary_format == 'dfrobot_lidar':
                return self._parse_binary_dfrobot_lidar(raw_data)
            
            # Gelecekte başka binary formatları buraya eklenebilir
            # elif binary_format == 'another_sensor':
            #     return self._parse_another_sensor(raw_data)

            else:
                print(f"     -> UYARI: Bilinmeyen binary formatı: {binary_format}")
                return None
        # --- BLOK BİTTİ ---

        elif parser_type == 'simple':
            return raw_data
        
        print(f"     -> UYARI: Bilinmeyen ayrıştırıcı tipi: {parser_type}")
        return None

    def _parse_binary_dfrobot_lidar(self, raw_data):
        """DFRobot Lidar'ın 4-byte'lık binary protokolünü işler."""
        if not isinstance(raw_data, bytes) or len(raw_data) < 4:
            return None
        
        start_index = raw_data.find(b'\xFF')
        if start_index == -1 or start_index + 4 > len(raw_data):
            return None
        
        packet = raw_data[start_index : start_index + 4]

        checksum = (packet[0] + packet[1] + packet[2]) & 0xFF
        if checksum != packet[3]:
            print("     -> Checksum hatası!")
            return None

        distance_mm = (packet[1] << 8) + packet[2]
        return {'distance_cm': round(distance_mm / 10.0, 1)}

    def _send_data_to_server(self, payload):
        try:
            response = requests.post(f"{self.base_url}/api/v3/readings/submit/", headers=self.headers, json=payload, timeout=10)
            return (True, "OK") if response.status_code == 201 else (False, f"Sunucu Hatası {response.status_code}")
        except requests.exceptions.RequestException as e:
            return False, "Bağlantı Hatası"

    def _queue_data_locally(self, payload):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.cursor().execute("INSERT INTO readings (payload) VALUES (?)", (json.dumps(payload),))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"   -> ❌ HATA: Veri yerel kuyruğa eklenemedi: {e}")

    def _process_offline_queue(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            queued_items = cursor.execute("SELECT id, payload FROM readings ORDER BY id ASC").fetchall()
            if queued_items:
                print(f"\n📬 Çevrimdışı kuyrukta {len(queued_items)} kayıt var, gönderiliyor...")
                for item in queued_items:
                    success, msg = self._send_data_to_server(json.loads(item['payload']))
                    if success:
                        print(f"   -> Kuyruk (ID: {item['id']}) gönderildi.")
                        cursor.execute("DELETE FROM readings WHERE id = ?", (item['id'],))
                        conn.commit()
                    else:
                        print("   -> Sunucuya ulaşılamıyor, kuyruk işlemi durduruldu.")
                        break
            conn.close()
        except Exception as e:
            print(f"   -> ❌ HATA: Kuyruk işlenemedi: {e}")

    def run(self):
        if not self.is_configured:
            print("❌ Agent, yerel konfigürasyon hatası nedeniyle başlatılamıyor.")
            sys.exit(1)
        if not self.get_server_configuration():
            print("❌ Agent, sunucuya bağlanamadığı için başlatılamıyor.")
            sys.exit(1)
        run_interval = 10
        print(f"\n⏰ Zamanlayıcı kuruldu. Ana döngü her {run_interval} saniyede bir çalışacak.")
        print("💡 Çıkmak için Ctrl+C'ye basın.")
        try:
            self.master_read_cycle()
            self.scheduler.add_job(self.master_read_cycle, 'interval', seconds=run_interval)
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\n🛑 Agent durduruluyor...")
            self.scheduler.shutdown()

# --- Script Başlangıç Kısmı ---

def check_and_install_dependencies():
    """ Gerekli temel kütüphanelerin yüklü olup olmadığını kontrol eder. """
    dependencies = ['requests', 'apscheduler']
    missing = []
    for package in dependencies:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"\nEksik kütüphaneler bulundu: {', '.join(missing)}. Yükleniyor...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing])
            print("✅ Gerekli kütüphaneler başarıyla yüklendi.")
        except subprocess.CalledProcessError as e:
            print(f"❌ HATA: Kütüphaneler yüklenemedi. Lütfen manuel yükleyin: 'pip install {' '.join(missing)}'. Hata: {e}")
            sys.exit(1)

if __name__ == "__main__":
    check_and_install_dependencies()
    agent = OrionAgent()
    agent.run()