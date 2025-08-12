import configparser
import json
import os
import sqlite3
import sys
import time
import importlib
from apscheduler.schedulers.blocking import BlockingScheduler
import requests

# Gerekli kütüphaneleri import etmeye çalış
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

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
        print("--- Bekleyen Komutlar Kontrol Ediliyor ---")
        self._check_and_execute_commands()
        print("--- Komut Kontrolü Tamamlandı ---")
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

    def _check_and_execute_commands(self):
        try:
            response = requests.get(f"{self.base_url}/api/v3/commands/", headers={'Authorization': self.headers['Authorization']}, timeout=10)
            if response.status_code != 200:
                print(f"  -> Komutlar alınamadı. Sunucu: {response.status_code}")
                return
            commands = response.json()
            if not commands:
                print("  -> Çalıştırılacak yeni komut yok.")
                return
            print(f"  -> {len(commands)} yeni komut bulundu.")
            for command in commands:
                success = False
                if command.get('command_type') == 'capture_photo':
                    success = self._execute_capture_photo(command.get('payload', {}))
                else:
                    print(f"     -> Bilinmeyen komut tipi: {command.get('command_type')}")
                    success = True
                if success:
                    self._mark_command_as_executed(command.get('id'))
        except requests.exceptions.RequestException as e:
            print(f"  -> HATA: Komut sunucusuna bağlanılamadı: {e}")

    def _execute_capture_photo(self, payload):
        if not OPENCV_AVAILABLE:
            print("     -> HATA: 'opencv-python' yüklü değil."); return False
        camera_id = payload.get('camera_id'); rtsp_url = payload.get('rtsp_url')
        if not all([camera_id, rtsp_url]):
            print("     -> HATA: 'capture_photo' komutunda eksik payload."); return True
        print(f"     -> Fotoğraf çekiliyor... (Kamera ID: {camera_id})")
        capture = cv2.VideoCapture(rtsp_url)
        if not capture.isOpened():
            print(f"     -> HATA: Kamera akışına bağlanılamadı: {rtsp_url}"); return False
        ret, frame = capture.read()
        capture.release()
        if not ret:
            print("     -> HATA: Kameradan kare alınamadı."); return False
        image_path = os.path.join(os.path.dirname(__file__), f"capture_{camera_id}.jpg")
        cv2.imwrite(image_path, frame)
        print(f"     -> Kare başarıyla '{os.path.basename(image_path)}' olarak kaydedildi.")
        return self._upload_capture(camera_id, image_path)

    def _upload_capture(self, camera_id, image_path):
        print("     -> Görüntü sunucuya yükleniyor...")
        try:
            with open(image_path, 'rb') as image_file:
                files = {'image': (os.path.basename(image_path), image_file, 'image/jpeg')}
                data = {'camera': camera_id}
                response = requests.post(f"{self.base_url}/api/v3/captures/", headers={'Authorization': self.headers['Authorization']}, data=data, files=files, timeout=30)
            os.remove(image_path)
            if response.status_code == 201:
                print("     -> ✅ Görüntü başarıyla yüklendi."); return True
            else:
                print(f"     -> ❌ HATA: Görüntü yüklenemedi. Sunucu: {response.status_code} - {response.text}"); return False
        except (IOError, requests.exceptions.RequestException) as e:
            print(f"     -> ❌ HATA: Görüntü yüklenirken hata: {e}")
            if os.path.exists(image_path): os.remove(image_path)
            return False

    def _mark_command_as_executed(self, command_id):
        try:
            response = requests.patch(f"{self.base_url}/api/v3/commands/{command_id}/", headers=self.headers, json={'is_executed': True})
            if response.status_code == 200:
                print(f"     -> Komut (ID: {command_id}) 'çalıştırıldı' olarak işaretlendi.")
            else:
                print(f"     -> UYARI: Komut işaretlenemedi. Sunucu: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"     -> HATA: Komut güncellenirken sunucuya bağlanılamadı: {e}")
    
    def _read_all_physical_sensors(self):
        sensors = [s for s in self.device_config.get('sensors', []) if s.get('is_active') and s.get('interface') != 'virtual']
        
        for sensor_config in sensors:
            print(f"  -> İşleniyor: {sensor_config['name']}")
            
            driver_name = sensor_config.get('parser_config', {}).get('driver')
            data = None

            if not driver_name:
                print("     -> UYARI: Bu sensör için bir 'driver' belirtilmemiş. Atlanıyor.")
                continue

            try:
                driver_module = importlib.import_module(f"drivers.{driver_name}")
                data = driver_module.read(sensor_config.get('config', {}))
            except ImportError:
                print(f"     -> HATA: Sürücü bulunamadı: 'drivers/{driver_name}.py'")
            except Exception as e:
                print(f"     -> HATA: Sürücü '{driver_name}' çalışırken hata oluştu: {e}")

            if data:
                print(f"     -> Okunan Veri: {data}")
                self.reading_cache[sensor_config['id']] = data
            else:
                print("     -> Veri okunamadı.")
                
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
    # Artık kütüphane kontrolüne gerek yok, manuel kuruldu.
    agent = OrionAgent()
    agent.run()