import configparser, requests, json, sys, time, os, sqlite3, re, struct
from apscheduler.schedulers.blocking import BlockingScheduler

try:
    import serial
    import serial.tools.list_ports
    import smbus2
    HARDWARE_LIBS_AVAILABLE = True
except ImportError:
    HARDWARE_LIBS_AVAILABLE = False
    print("⚠️ UYARI: 'pyserial' veya 'smbus2' kütüphaneleri bulunamadı. Sadece sanal sensörler çalışacaktır.")


class OrionAgent:
    def __init__(self, config_file='config.ini'):
        # ... (__init__ metodu, veritabanı ve temel ayarlar için aynı kalıyor) ...
        self.config = self._load_ini_config(config_file)
        if not self.config: self.is_configured = False; return
        self.base_url = self.config['server']['base_url']
        self.token = self.config['device']['token']
        self.headers = {'Authorization': f'Token {self.token}', 'Content-Type': 'application/json'}
        self.device_config = None; self.is_configured = True
        self.scheduler = BlockingScheduler(timezone="Europe/Istanbul")
        self.db_path = os.path.join(os.path.dirname(__file__), 'offline_queue.db')
        self._init_local_db()
        # Okuma döngüsü içinde toplanan verileri sanal sensörler için saklayacak önbellek
        self.reading_cache = {}
        print("✅ Agent başlatıldı ve yerel konfigürasyon yüklendi.")

    # --- Okuma, Ayrıştırma ve Hesaplama Motorları (YENİ ve GÜNCELLENMİŞ) ---
    def _read_physical_sensor(self, sensor_config):
        """Arayüz tipine göre ilgili donanım okuma fonksiyonunu çağırır."""
        if not HARDWARE_LIBS_AVAILABLE:
            print(f"   -> Donanım kütüphaneleri eksik, '{sensor_config['name']}' sensörü okunamıyor.")
            return None

        interface = sensor_config.get('interface')
        if interface == 'serial':
            return self._read_serial_sensor(sensor_config)
        elif interface == 'i2c':
            return self._read_i2c_sensor(sensor_config)
        else:
            print(f"   -> Desteklenmeyen arayüz: '{interface}'")
            return None

    def _read_serial_sensor(self, sensor_config):
        """VID ve PID kullanarak doğru seri portu bulur ve veri okur."""
        conf = sensor_config.get('config', {})
        vid = conf.get('vid')
        pid = conf.get('pid')
        baudrate = conf.get('baudrate', 9600)

        if not vid or not pid:
            print("   -> HATA: Seri sensör için 'vid' ve 'pid' yapılandırması eksik.")
            return None
        
        port_to_use = None
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if port.vid == vid and port.pid == pid:
                port_to_use = port.device
                break
        
        if not port_to_use:
            print(f"   -> HATA: VID={vid}, PID={pid} ile eşleşen bir seri port bulunamadı.")
            return None
            
        try:
            with serial.Serial(port_to_use, baudrate, timeout=2) as ser:
                print(f"   -> Seri port '{port_to_use}' açıldı. Veri bekleniyor...")
                time.sleep(2) # Sensörün veri göndermeye başlaması için bekle
                raw_data = ser.read(100).decode('utf-8', errors='ignore').strip()
                print(f"   -> Ham Veri Alındı: '{raw_data}'")
                return raw_data
        except serial.SerialException as e:
            print(f"   -> HATA: Seri port '{port_to_use}' okunurken hata: {e}")
            return None

    def _read_i2c_sensor(self, sensor_config):
        """Belirtilen I2C adresinden veri okur."""
        conf = sensor_config.get('config', {})
        address_str = conf.get('address')
        if not address_str:
            print("   -> HATA: I2C sensör için 'address' yapılandırması eksik.")
            return None
        
        try:
            address = int(address_str, 16) # "0x44" gibi bir string'i sayıya çevir
            # SHT3x için 6 byte oku
            with smbus2.SMBus(1) as bus:
                # Ölçüm komutu gönder
                bus.write_i2c_block_data(address, 0x2C, [0x06])
                time.sleep(0.5) # Ölçüm için bekle
                # 6 byte'lık veriyi oku
                raw_data = bus.read_i2c_block_data(address, 0x00, 6)
                print(f"   -> Ham Veri Alındı (I2C): {list(raw_data)}")
                return bytes(raw_data)
        except Exception as e:
            print(f"   -> HATA: I2C adresi '{address_str}' okunurken hata: {e}")
            return None

    def _parse_data(self, raw_data, sensor_config):
        """Ayrıştırıcı tipine göre ham veriyi işler."""
        parser_type = sensor_config.get('parser_type')
        parser_config = sensor_config.get('parser_config', {})
        
        if parser_type == 'regex':
            return self._parse_with_regex(raw_data, parser_config)
        elif parser_type == 'binary':
            return self._parse_with_binary(raw_data, parser_config)
        elif parser_type == 'simple':
            return {'value': raw_data} # Basitçe ham veriyi paketle
        else:
            print(f"   -> Desteklenmeyen ayrıştırıcı: '{parser_type}'")
            return None

    def _parse_with_regex(self, raw_data, p_conf):
        rule = p_conf.get('rule')
        mapping = p_conf.get('output_mapping')
        if not rule or not mapping or not isinstance(raw_data, str): return None
        
        # En son satırı alarak kısmi veri okuma sorununu çözmeye çalışalım
        last_line = raw_data.strip().split('\n')[-1]
        match = re.search(rule, last_line)
        if not match: return None
        
        result = {}
        for group_key, output_key in mapping.items():
            try:
                group_index = int(group_key.split('_')[1])
                value = match.group(group_index)
                result[output_key] = float(value)
            except (ValueError, IndexError, TypeError):
                continue
        return result if result else None
    
    def _parse_with_binary(self, raw_data, p_conf):
        format_rule = p_conf.get('format')
        mapping = p_conf.get('output_mapping', {})
        if not format_rule or not isinstance(raw_data, bytes): return None

        if format_rule == 'SHT3X_6BYTE':
            if len(raw_data) != 6: return None
            result = {}
            for key, rules in mapping.items():
                formula = rules.get('formula')
                if formula:
                    try:
                        # Eval'i güvenli bir context'te çalıştır
                        value = eval(formula, {"__builtins__": None}, {"bytes": raw_data})
                        result[key] = round(value, 2)
                    except Exception as e:
                        print(f"   -> HATA: Binary formülü ('{key}') hesaplanırken hata: {e}")
            return result
        return None

    def _calculate_virtual_sensor(self, sensor_config):
        """Sanal sensörün değerini önbellekteki verilerden hesaplar."""
        conf = sensor_config.get('config', {})
        formula = conf.get('formula')
        input_keys = conf.get('input_keys', [])
        output_key = conf.get('output_key', 'value')

        if not formula or not input_keys: return None

        # Gerekli girdiler önbellekte var mı?
        if not all(key in self.reading_cache for key in input_keys):
            print(f"   -> Sanal sensör için gerekli girdiler ({input_keys}) önbellekte bulunamadı.")
            return None
        
        try:
            # Sadece gerekli girdileri formül context'ine koy
            context = {key: self.reading_cache[key] for key in input_keys}
            result = eval(formula, {"__builtins__": None}, context)
            return {output_key: round(result, 2)}
        except Exception as e:
            print(f"   -> HATA: Sanal sensör formülü hesaplanırken hata: {e}")
            return None
            
    # --- Ana Döngü ve Sunucu İletişimi (GÜNCELLENMİŞ) ---
    def master_read_cycle(self):
        """Ana okuma döngüsü: Önce kuyruğu işle, sonra SENSÖRLERİ OKU."""
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n🔄 ({ts}) Ana okuma döngüsü çalıştı.")
        
        self.reading_cache.clear() # Her döngü başında önbelleği temizle
        self._process_offline_queue()

        if not self.device_config or not self.device_config.get('sensors'):
            print("   -> Sunucudan sensör yapılandırması alınamadı, döngü atlanıyor.")
            return

        all_sensors = self.device_config['sensors']
        physical_sensors = [s for s in all_sensors if s.get('interface') != 'virtual' and s.get('is_active')]
        virtual_sensors = [s for s in all_sensors if s.get('interface') == 'virtual' and s.get('is_active')]

        # 1. Önce fiziksel sensörleri oku ve sonuçları önbelleğe al
        print("\n--- Fiziksel Sensörler Okunuyor ---")
        for sensor in physical_sensors:
            print(f"-> İşleniyor: {sensor['name']}")
            raw_data = self._read_physical_sensor(sensor)
            if raw_data is not None:
                processed_data = self._parse_data(raw_data, sensor)
                if processed_data:
                    self.reading_cache.update(processed_data)
                    self._submit_data(sensor['id'], processed_data)

        # 2. Sonra sanal sensörleri hesapla
        print("\n--- Sanal Sensörler Hesaplanıyor ---")
        for sensor in virtual_sensors:
            print(f"-> İşleniyor: {sensor['name']}")
            calculated_data = self._calculate_virtual_sensor(sensor)
            if calculated_data:
                self.reading_cache.update(calculated_data) # Gelecekte başka bir sanal sensör bunu kullanabilir
                self._submit_data(sensor['id'], calculated_data)

    def _submit_data(self, sensor_id, value_dict):
        """Veriyi ya sunucuya gönderir ya da yerel kuyruğa atar."""
        payload = {"sensor": sensor_id, "value": value_dict}
        print(f"   -> Sonuç: {json.dumps(payload)}")
        success, message = self._send_data_to_server(payload)
        if success:
            print(f"   -> ✅ {message}")
        else:
            print(f"   -> ❌ Sunucuya gönderilemedi. Sebep: {message.split('(')[0]}")
            self._queue_data_locally(payload)
    
    # ... (_init_local_db, _load_ini_config, get_server_configuration,
    # _send_data_to_server, _queue_data_locally, _process_offline_queue, run,
    # check_and_install_dependencies fonksiyonları büyük ölçüde aynı kalıyor.
    # Sadece run'dan 'sensor_to_use' kısmını çıkarabiliriz.)
    
    def run(self):
        if not self.is_configured: sys.exit(1)
        print("\n" + "="*50 + "\n🚀 Orion Agent v3.0 - Faz 4.1 Başlatılıyor...\n" + "="*50)

        if not self.get_server_configuration():
            print("\n🛑 Agent, başlangıçta sunucudan yapılandırma alamadığı için durduruluyor.")
            # Gelecekte burada lokal konfigürasyondan çalışma özelliği eklenebilir.
            sys.exit(1)

        # En kısa okuma aralığını bularak ana döngü sıklığını belirle
        intervals = [s.get('read_interval', 60) for s in self.device_config.get('sensors', []) if s.get('is_active')]
        run_interval = min(intervals) if intervals else 60
        
        self.scheduler.add_job(self.master_read_cycle, 'interval', seconds=run_interval, id='master_cycle')
        print(f"\n⏰ Zamanlayıcı kuruldu. Ana okuma döngüsü her {run_interval} saniyede bir çalışacak.")
        print("💡 Çıkmak için Ctrl+C'ye basın.")
        
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\n🛑 Agent durduruluyor...")
    
    # Geri kalan tüm yardımcı fonksiyonlar (veritabanı, sunucu iletişimi vb.)
    # bir önceki adımdaki ile aynı. Kodu kısaltmak için buraya eklemiyorum,
    # ama yukarıdaki tam kodda hepsi mevcut.