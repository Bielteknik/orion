import configparser
import json
import os
import re
import sqlite3
import sys
import time
import subprocess
import importlib
from apscheduler.schedulers.blocking import BlockingScheduler
import requests

# --- Donanım Kütüphaneleri ---
# Bu kütüphaneler sadece Raspberry Pi üzerinde bulunur.
# Hata vermemesi için try-except bloğu içinde import ediyoruz.
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

# --- Ana Orkestra Şefi Sınıfı ---
class OrionAgent:
    """
    Orion Projesi v3.0 için ana istemci.
    Sensörleri sunucudan aldığı dinamik konfigürasyona göre okur,
    işler, çevrimdışı durumları yönetir ve sunucuya gönderir.
    """
    def __init__(self, config_file='config.ini'):
        print("--- Orion Agent Başlatılıyor ---")
        self.is_configured = False
        
        # 1. Yerel konfigürasyonu yükle
        local_config = self._load_ini_config(config_file)
        if not local_config:
            return

        self.base_url = local_config['server']['base_url']
        self.token = local_config['device']['token']
        self.headers = {'Authorization': f'Token {self.token}', 'Content-Type': 'application/json'}
        
        # 2. Yerel veritabanını (çevrimdışı kuyruk) hazırla
        self.db_path = os.path.join(os.path.dirname(__file__), 'offline_queue.db')
        if not self._init_local_db():
            return
            
        # 3. Agent'ın çalışma zamanı değişkenlerini tanımla
        self.device_config = None
        self.scheduler = BlockingScheduler(timezone="Europe/Istanbul")
        self.reading_cache = {}
        
        self.is_configured = True
        print("✅ Agent başlatılmaya hazır.")

    # --- Başlangıç ve Yapılandırma Metotları ---
    
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
        try:
            response = requests.get(f"{self.base_url}/api/v3/device/config/", headers=self.headers, timeout=10)
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

    # --- Ana Çalışma Döngüsü ---

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

    # --- Sensör Okuma Motoru (Artık Sürücüleri Çağırıyor) ---
    
    def _read_all_physical_sensors(self):
        sensors = [s for s in self.device_config.get('sensors', []) if s.get('is_active') and s.get('interface') != 'virtual']
        
        for sensor_config in sensors:
            print(f"  -> İşleniyor: {sensor_config['name']}")
            
            # 1. Sürücüyü Bul ve Yükle (Eğer belirtilmişse)
            driver_name = sensor_config.get('parser_config', {}).get('driver')
            data = None

            if driver_name:
                try:
                    driver_module = importlib.import_module(f"drivers.{driver_name}")
                    data = driver_module.read(sensor_config.get('config', {}))
                except ImportError:
                    print(f"     -> HATA: Sürücü bulunamadı: 'drivers/{driver_name}.py'")
                except Exception as e:
                    print(f"     -> HATA: Sürücü çalışırken hata oluştu: {e}")
            
            # Sürücü tabanlı olmayanlar için eski yöntem (örn: I2C)
            elif sensor_config.get('interface') == 'i2c':
                data = self._read_i2c(sensor_config.get('config', {}))
            else:
                print("     -> UYARI: Bu sensör için bir 'driver' belirtilmemiş.")
                continue

            if data:
                print(f"     -> Okunan Veri: {data}")
                self.reading_cache[sensor_config['id']] = data
            else:
                print("     -> Veri okunamadı.")
                
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

    # --- Çevrimdışı Kuyruk ve Sunucu İletişimi ---

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

    # --- Ana Çalıştırma Fonksiyonu ---

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

# --- Script Başlangıç Kısmı ---

def check_and_install_dependencies():
    """ Gerekli temel kütüphanelerin yüklü olup olmadığını kontrol eder, eksikse yükler. """
    base_dependencies = ['requests', 'apscheduler']
    if sys.platform.startswith('linux'):
        base_dependencies.extend(['pyserial', 'smbus2'])
    
    missing_packages = []
    for package_name in base_dependencies:
        try:
            __import__(package_name)
        except ImportError:
            missing_packages.append(package_name)

    if missing_packages:
        print(f"\nEksik kütüphaneler bulundu: {', '.join(missing_packages)}. Yükleniyor...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing_packages])
            print("✅ Gerekli kütüphaneler başarıyla kuruldu.")
            print("Lütfen script'i tekrar çalıştırın.")
            sys.exit(0)
        except subprocess.CalledProcessError as e:
            print(f"❌ HATA: Kütüphaneler yüklenemedi. Lütfen manuel yükleyin: 'pip install {' '.join(missing_packages)}'. Hata: {e}")
            sys.exit(1)

if __name__ == "__main__":
    check_and_install_dependencies()
    agent = OrionAgent()
    agent.run()