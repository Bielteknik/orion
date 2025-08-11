import serial
import time

# Seri port ayarları
SERIAL_PORT = '/dev/ttyAGIRLIK'
BAUD_RATE = 9600

# Seri portu aç
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

try:
    while True:
        if ser.in_waiting > 0:
            data = ser.readline().decode('utf-8').rstrip()
            print(data)
        time.sleep(0.1)  # CPU yükünü azaltmak için küçük bir bekleme
except KeyboardInterrupt:
    print("Program durduruldu.")
finally:
    ser.close()