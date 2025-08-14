import cv2
import threading
import time
from django.http import StreamingHttpResponse, HttpResponse
from .models import Camera

class VideoCamera:
    def __init__(self, rtsp_url):
        print(f"Kamera başlatılıyor: {rtsp_url}")
        self.video = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        self.is_running = self.video.isOpened() # Başlangıçta bağlantı durumunu kontrol et
        
        if not self.is_running:
            print(f"HATA: Kamera akışına bağlanılamadı: {rtsp_url}")
            return

        self.grabbed, self.frame = self.video.read()
        if not self.grabbed:
            print("HATA: İlk kare alınamadı.")
            self.is_running = False
            self.video.release()
            return
            
        self.lock = threading.Lock()
        threading.Thread(target=self.update, args=(), daemon=True).start()

    def __del__(self):
        if self.video.isOpened():
            self.video.release()

    def get_frame(self):
        if not self.is_running:
            return None
        with self.lock:
            if not self.grabbed: return None
            frame_copy = self.frame.copy()
        
        ret, jpeg = cv2.imencode('.jpg', frame_copy)
        return jpeg.tobytes() if ret else None

    def update(self):
        while self.is_running:
            grabbed, frame = self.video.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
            if not grabbed:
                print("UYARI: Kamera akışı kesildi.")
                self.is_running = False
                break
            time.sleep(0.03) # ~30fps için

def gen(camera):
    while camera.is_running:
        frame = camera.get_frame()
        if frame is None:
            break
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
    print("Yayın sonlandırıldı.")

def camera_feed(request, pk):
    try:
        camera_obj = Camera.objects.get(pk=pk, status='active')
        cam = VideoCamera(camera_obj.rtsp_url)
        
        # DÜZELTME: Kamera bağlantısı başlangıçta başarısız olduysa, hata döndür.
        if not cam.is_running:
            return HttpResponse(f"Kamera akışına bağlanılamadı. Lütfen RTSP URL'ini kontrol edin: {camera_obj.rtsp_url}", status=503) # 503 Service Unavailable

        return StreamingHttpResponse(gen(cam), content_type='multipart/x-mixed-replace; boundary=frame')
    except Camera.DoesNotExist:
        return HttpResponse("Kamera bulunamadı veya aktif değil.", status=404)
    except Exception as e:
        print(f"Kamera yayını hatası: {e}")
        return HttpResponse(f"Yayın başlatılamadı: {e}", status=500)