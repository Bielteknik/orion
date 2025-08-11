import time

# Bu sürücü, agent.py'deki global SMBUS_AVAILABLE değişkenini kullanmayacak.
# Kendi içinde import'u yönetmesi daha temizdir.
try:
    from smbus2 import SMBus, i2c_msg
    SMBUS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    SMBUS_AVAILABLE = False

def read(config):
    """
    SHT3x gibi bir I2C sıcaklık/nem sensöründen veri okur.
    'config' sözlüğü, {'address': '0x44', 'bus': 1} gibi ayarları içerir.
    """
    if not SMBUS_AVAILABLE:
        print("     -> UYARI (SHT3x): 'smbus2' kütüphanesi yüklü değil, okuma atlanıyor.")
        return None

    address_str = config.get('address')
    bus_num = config.get('bus', 1)
    if not address_str:
        print("     -> HATA (SHT3x): Adres (address) belirtilmemiş.")
        return None

    try:
        i2c_addr = int(str(address_str), 16)
        
        with SMBus(bus_num) as bus:
            # SHT3x için yüksek tekrarlanabilirlikli okuma komutları
            write = i2c_msg.write(i2c_addr, [0x2C, 0x06])
            read = i2c_msg.read(i2c_addr, 6)
            
            bus.i2c_rdwr(write)
            time.sleep(0.5)
            bus.i2c_rdwr(read)
            
            data = list(read)
            
            # Veriyi hesapla
            temp = -45 + (175 * (data[0] * 256 + data[1])) / 65535.0
            humidity = 100 * (data[3] * 256 + data[4]) / 65535.0
            
            return {'temperature': round(temp, 2), 'humidity': round(humidity, 2)}
            
    except (OSError, ValueError) as e:
        print(f"     -> HATA (SHT3x): I2C sensöründen okunamadı (Adres: {address_str}): {e}")
        return None