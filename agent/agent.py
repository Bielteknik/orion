import configparser
import requests
import json
import sys
import time
import random
import sqlite3 # YENİ: Yerel veritabanı için
import os      # YENİ: Dosya yolu için
from apscheduler.schedulers.blocking import BlockingScheduler

class OrionAgent:
    def __init__(self, config_file='config.ini'):
        self.config = self._load_ini_config(config_file)
        if not self.config:
            self.is_configured = False
            return

        self.base_url = self.config['server']['base_url']
        self.token = self.config['device']['token']
        self.headers = {
            'Authorization': f'Token {self.token}',
            'Content-Type': 'application/json'
        }
        
        self.device_config = None
        self.is_configured = True
        self.scheduler = BlockingScheduler(timezone="Europe/Istanbul")
        self.sensor_to_use = None
        
        # YENİ: Çevrimdışı kuyruk için veritabanı ayarları
        self.db_path = os.path.join(os.path.dirname(__file__), 'offline_queue.db')
        self._init_local_db()
        
        print("✅ Agent başlatıldı ve yerel konfigürasyon yüklendi.")

    # YENİ: Yerel veritabanını ve tabloyu oluşturan fonksiyon
    def _init_local_db(self):
        """Yerel SQLite veritabanını ve 'readings' tablosunu oluşturur."""
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
            print("✅ Yerel çevrimdışı kuyruk veritabanı hazır.")
        except Exception as e:
            print(f"❌ HATA: Yerel veritabanı oluşturulamadı: {e}")
            sys.exit(1)

    def _load_ini_config(self, config_file):
        """ .ini dosyasından yapılandırmayı okur. """
        try:
            parser = configparser.ConfigParser()
            if not parser.read(config_file, encoding='utf-8'):
                print(f"❌ HATA: Konfigürasyon dosyası bulunamadı veya boş: '{config_file}'")
                return None
            return {section: dict(parser.items(section)) for section in parser.sections()}
        except Exception as e:
            print(f"❌ HATA: Konfigürasyon dosyası okunamadı! Hata: {e}")
            return None

    def get_server_configuration(self):
        # Bu fonksiyon aynı, değişiklik yok
        config_url = f"{self.base_url}/api/v3/device/config/"
        print(f"📡 Sunucudan yapılandırma isteniyor: {config_url}")
        try:
            response = requests.get(config_url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                self.device_config = response.json()
                print("✅ Sunucu yapılandırması başarıyla alındı.")
                return True
            else:
                print(f"❌ HATA: Konfigürasyon alınamadı. Sunucu yanıtı: Status {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ HATA: Sunucuya bağlanılamadı! Detay: {e}")
            return False

    # YENİ: Veriyi doğrudan sunucuya göndermeyi deneyen fonksiyon
    def _send_data_to_server(self, payload_to_send):
        """Verilen payload'ı sunucuya göndermeyi dener, başarı durumunu döndürür."""
        submit_url = f"{self.base_url}/api/v3/readings/submit/"
        try:
            response = requests.post(submit_url, headers=self.headers, json=payload_to_send, timeout=10)
            if response.status_code == 201:
                return True, "Başarıyla gönderildi."
            else:
                error_message = f"Sunucu hatası: {response.status_code} - {response.text}"
                return False, error_message
        except requests.exceptions.RequestException as e:
            error_message = f"Bağlantı hatası: {e}"
            return False, error_message

    # YENİ: Veriyi yerel kuyruğa ekleyen fonksiyon
    def _queue_data_locally(self, payload_to_queue):
        """Verilen payload'ı yerel SQLite veritabanına kaydeder."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Payload'ı string formatında kaydediyoruz
            cursor.execute("INSERT INTO readings (payload) VALUES (?)", (json.dumps(payload_to_queue),))
            conn.commit()
            conn.close()
            print(f"   -> 💾 Veri yerel kuyruğa eklendi.")
        except Exception as e:
            print(f"   -> ❌ HATA: Veri yerel kuyruğa eklenemedi: {e}")

    # YENİ: Yerel kuyruktaki verileri göndermeyi deneyen fonksiyon
    def _process_offline_queue(self):
        """Kuyruktaki verileri okur ve sunucuya göndermeyi dener."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # Sütun adlarıyla erişim için
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, payload FROM readings ORDER BY id ASC")
        queued_items = cursor.fetchall()

        if not queued_items:
            conn.close()
            return
            
        print(f"   -> 📬 Çevrimdışı kuyrukta {len(queued_items)} kayıt bulundu. Gönderiliyor...")
        
        for item in queued_items:
            payload_id = item['id']
            payload_data = json.loads(item['payload'])
            
            success, message = self._send_data_to_server(payload_data)
            
            if success:
                print(f"      -> Kuyruk (ID: {payload_id}) başarıyla gönderildi.")
                # Başarılı gönderilen kaydı kuyruktan sil
                cursor.execute("DELETE FROM readings WHERE id = ?", (payload_id,))
                conn.commit()
            else:
                print(f"      -> Kuyruk gönderilemedi. Sunucu ulaşılamıyor. Deneme durduruldu.")
                # Sunucuya ulaşılamıyorsa, döngüyü kır ve daha sonra tekrar dene.
                break
        
        conn.close()

    # GÜNCELLENDİ: Ana döngünün mantığı tamamen değişti
    def master_read_cycle(self):
        """Ana okuma döngüsü: Önce kuyruğu işle, sonra yeni veriyi oku."""
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n🔄 ({ts}) Ana okuma döngüsü çalıştı.")

        # 1. Önce her zaman yerel kuyruğu işlemeyi dene
        self._process_offline_queue()

        # 2. Yeni sensör verisini oluştur
        if not self.sensor_to_use:
            print("   -> Gönderilecek sensör bulunamadı. Yeni veri okunmuyor.")
            return

        fake_temperature = round(random.uniform(15.0, 25.0), 2)
        fake_humidity = round(random.uniform(40.0, 60.0), 2)
        
        current_payload = {
            "sensor": self.sensor_to_use['id'],
            "value": { "temperature": fake_temperature, "humidity": fake_humidity }
        }
        print(f"   -> Mevcut Okuma: {json.dumps(current_payload)}")

        # 3. Yeni veriyi doğrudan göndermeyi dene
        success, message = self._send_data_to_server(current_payload)
        
        if success:
            print(f"   -> ✅ {message}")
        else:
            # Başarısız olursa, yerel kuyruğa at
            print(f"   -> ❌ Sunucuya gönderilemedi. Sebep: {message.split('(')[0]}")
            self._queue_data_locally(current_payload)

    def run(self):
        # Bu fonksiyonun içeriği bir önceki adımla aynı, değişiklik yok.
        # ... (değişiklik yok) ...
        if not self.is_configured:
            print("Yerel konfigürasyon yüklenemediği için Agent çalıştırılamıyor.")
            sys.exit(1)

        print("\n" + "="*50)
        print("🚀 Orion Agent v3.0 - Faz 1.5 Başlatılıyor...")
        print("="*50)

        if not self.get_server_configuration():
            print("\n🛑 Agent, başlangıçta sunucudan yapılandırma alamadığı için durduruluyor.")
            sys.exit(1)
        
        if self.device_config.get('sensors'):
            self.sensor_to_use = self.device_config['sensors'][0]
            print(f"\nℹ️  Veri göndermek için '{self.sensor_to_use['name']}' (ID: {self.sensor_to_use['id']}) sensörü kullanılacak.")
        else:
            print("\n⚠️  UYARI: Cihaza atanmış aktif sensör bulunamadı. Veri gönderimi yapılmayacak.")
            print("   -> Lütfen admin panelinden bu cihaza bir sensör ekleyin.")

        run_interval = 10
        self.scheduler.add_job(self.master_read_cycle, 'interval', seconds=run_interval, id='master_cycle')
        print(f"\n⏰ Zamanlayıcı kuruldu. Ana okuma döngüsü her {run_interval} saniyede bir çalışacak.")
        print("💡 Çıkmak için Ctrl+C'ye basın.")
        
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\n🛑 Agent durduruluyor...")

def check_and_install_dependencies():
    # Bu fonksiyonun içeriği bir önceki adımla aynı, değişiklik yok.
    # ... (değişiklik yok) ...
    try:
        import apscheduler
        import requests
    except ImportError:
        print("\n'apscheduler' veya 'requests' kütüphanesi bulunamadı. Yükleniyor...")
        import subprocess
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'apscheduler', 'requests'])
            print("✅ Gerekli kütüphaneler başarıyla yüklendi.")
        except subprocess.CalledProcessError as e:
            print(f"❌ HATA: Kütüphaneler yüklenemedi. Lütfen manuel olarak yükleyin: 'pip install apscheduler requests'. Hata: {e}")
            sys.exit(1)

if __name__ == "__main__":
    check_and_install_dependencies()
    agent = OrionAgent()
    agent.run()