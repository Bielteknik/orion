import configparser
import requests
import json
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler

class OrionAgent:
    """
    Orion Projesi için temel istemci.
    Sunucudan yapılandırma alır ve sensör okuma döngülerini yönetir.
    """
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
        print("✅ Agent başlatıldı ve yerel konfigürasyon yüklendi.")

    def _load_ini_config(self, config_file):
        """.ini dosyasından yapılandırmayı okur."""
        try:
            parser = configparser.ConfigParser()
            if not parser.read(config_file, encoding='utf-8'):
                print(f"❌ HATA: Konfigürasyon dosyası bulunamadı veya boş: '{config_file}'")
                return None
            config_data = {section: dict(parser.items(section)) for section in parser.sections()}
            return config_data
        except Exception as e:
            print(f"❌ HATA: Konfigürasyon dosyası okunamadı! Hata: {e}")
            return None

    def get_server_configuration(self):
        """Sunucuya bağlanarak cihaza özel yapılandırma verilerini çeker."""
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

    def master_read_cycle(self):
        """
        Tüm sensör okuma, işleme ve gönderme döngüsünü yönetir.
        Bu fonksiyon, zamanlayıcı tarafından periyodik olarak çağrılacak.
        Şimdilik sadece bir mesaj basacak.
        """
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n🔄 ({ts}) Ana okuma döngüsü çalıştı.")
        # Gelecekteki adımlarda burayı sensör okuma mantığı ile dolduracağız.
        print("   -> (Henüz sensör okuma mantığı eklenmedi)")

    def run(self):
        """Agent'ın ana çalışma fonksiyonu."""
        if not self.is_configured:
            print("Yerel konfigürasyon yüklenemediği için Agent çalıştırılamıyor.")
            sys.exit(1)

        print("\n" + "="*50)
        print("🚀 Orion Agent v3.0 - Faz 1.3 Başlatılıyor...")
        print("="*50)

        # Başlangıçta sunucudan konfigürasyonu almayı dene
        if not self.get_server_configuration():
            print("\n🛑 Agent, başlangıçta sunucudan yapılandırma alamadığı için durduruluyor.")
            sys.exit(1)
        
        print("\n--- Alınan Cihaz Konfigürasyonu ---")
        print(json.dumps(self.device_config, indent=2, ensure_ascii=False))
        print("------------------------------------\n")
        
        # Zamanlayıcıyı kur
        # Şimdilik 10 saniyede bir çalışacak şekilde ayarlayalım
        run_interval = 10 
        self.scheduler.add_job(
            self.master_read_cycle, 
            'interval', 
            seconds=run_interval, 
            id='master_cycle'
        )
        print(f"⏰ Zamanlayıcı kuruldu. Ana okuma döngüsü her {run_interval} saniyede bir çalışacak.")
        print("💡 Çıkmak için Ctrl+C'ye basın.")
        
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\n🛑 Agent durduruluyor...")

if __name__ == "__main__":
    # Zamanlayıcı kütüphanesini de yüklememiz gerekecek
    try:
        import apscheduler
    except ImportError:
        print("\n'apscheduler' kütüphanesi bulunamadı. Yükleniyor...")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'apscheduler'])
        
    agent = OrionAgent()
    agent.run()