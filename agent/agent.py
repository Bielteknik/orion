import configparser
import json
import os
import sqlite3
import sys
import time
import importlib # Sürücüleri dinamik olarak yüklemek için
from apscheduler.schedulers.blocking import BlockingScheduler
import requests

# --- Donanım Kütüphaneleri (Sadece sürücüler tarafından kullanılacak) ---
try:
    from smbus2 import SMBus, i2c_msg
    SMBUS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    SMBUS_AVAILABLE = False

# --- Ana Orkestra Şefi Sınıfı ---
class OrionAgent:
    def __init__(self, config_file='config.ini'):
        # ... (init metodu bir önceki versiyonla aynı, SADECE self.reading_cache = {} satırını bırak) ...
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

    # ... (_load_ini_config, _init_local_db, get_server_configuration,
    #      _send_data_to_server, _queue_data_locally, _process_offline_queue
    #      fonksiyonları BİREBİR AYNI KALIYOR) ...

    def master_read_cycle(self):
        # ... (bu fonksiyonun yapısı aynı kalıyor, sadece _read_all_physical_sensors çağrısı var) ...
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
    
    # GÜNCELLENDİ: Bu fonksiyon artık sürücüleri çağırıyor.
    def _read_all_physical_sensors(self):
        sensors = [s for s in self.device_config.get('sensors', []) if s.get('is_active') and s.get('interface') != 'virtual']
        
        for sensor_config in sensors:
            print(f"  -> İşleniyor: {sensor_config['name']}")
            
            # 1. Sürücüyü Bul ve Yükle
            driver_name = sensor_config.get('parser_config', {}).get('driver')
            
            data = None
            if driver_name:
                try:
                    # 'drivers.hx711_load_cell' gibi bir modülü dinamik olarak import et
                    driver_module = importlib.import_module(f"drivers.{driver_name}")
                    # Sürücünün read() fonksiyonunu çağır
                    data = driver_module.read(sensor_config.get('config', {}))
                except ImportError:
                    print(f"     -> HATA: Sürücü bulunamadı: '{driver_name}.py'")
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
                
    # _read_i2c fonksiyonu aynı kalabilir veya o da kendi sürücüsüne taşınabilir. Şimdilik kalsın.
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

    def run(self):
        # ... (run metodu aynı kalıyor) ...
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