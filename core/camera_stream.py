import cv2
import threading
from django.http import StreamingHttpResponse
from .models import Camera

from django.http import HttpResponse

class VideoCamera:
    def __init__(self, rtsp_url):
        self.video = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        self.grabbed, self.frame = self.video.read()
        self.lock = threading.Lock()
        
        # Ayrı bir thread'de sürekli kare okumayı başlat
        threading.Thread(target=self.update, args=(), daemon=True).start()

    def __del__(self):
        self.video.release()

    def get_frame(self):
        with self.lock:
            # En son okunan kareyi kopyala ve döndür
            frame_copy = self.frame.copy() if self.grabbed else None
        
        if frame_copy is None:
            return None

        # Kareyi JPEG formatına çevir
        _, jpeg = cv2.imencode('.jpg', frame_copy)
        return jpeg.tobytes()

    def update(self):
        # Arka planda sürekli kare okuyan fonksiyon
        while True:
            grabbed, frame = self.video.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame

def gen(camera):
    while True:
        frame = camera.get_frame()
        if frame is None:
            # Kamera bağlantısı koparsa veya kare alınamazsa döngüden çık
            # Burada alternatif olarak "bağlantı yok" resmi de gönderilebilir
            break

        # HTTP multipart response formatında kareyi gönder
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

def camera_feed(request, pk):
    try:
        camera_obj = Camera.objects.get(pk=pk, status='active')
        cam = VideoCamera(camera_obj.rtsp_url)
        return StreamingHttpResponse(gen(cam), content_type='multipart/x-mixed-replace; boundary=frame')
    except Camera.DoesNotExist:
        # Kamera bulunamazsa veya aktif değilse 404 döndür
        return HttpResponse("Kamera bulunamadı veya aktif değil.", status=404)
    except Exception as e:
        print(f"Kamera yayını hatası: {e}")
        return HttpResponse(f"Yayın başlatılamadı: {e}", status=500)