import logging
from pathlib import Path
import numpy as np

from config import IMAGE_MIN_BRIGHTNESS, IMAGE_MOTION_BLUR_THRESHOLD
from core.models import PipelineState

logger = logging.getLogger(__name__)

class FrameExtractor:
    def __init__(self, video_path: Path):
        self.video_path = video_path
        self.available = False
        self.cv2 = None
        self.face_cascade = None
        
        try:
            import cv2
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(str(video_path))
            self.available = self.cap.isOpened()
            if not self.available:
                logger.error(f"Failed to open video: {video_path}")
            
            # Load face cascade safely
            if hasattr(cv2, 'CascadeClassifier') and hasattr(cv2, 'data') and hasattr(cv2.data, 'haarcascades'):
                try:
                    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                    self.face_cascade = cv2.CascadeClassifier(cascade_path)
                except Exception as e:
                    logger.warning(f"Could not load face cascade: {e}")
        except ImportError:
            logger.warning("OpenCV not installed. Frame extraction disabled.")
            self.cv2 = None

    def extract_frame(self, timestamp_sec: float) -> np.ndarray:
        if not self.available or self.cv2 is None:
            return None
        try:
            self.cap.set(self.cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
            ret, frame = self.cap.read()
            if ret:
                return frame
        except Exception as e:
            logger.warning(f"Error reading frame at {timestamp_sec:.2f}s: {e}")
        return None

    def is_good_frame(self, frame: np.ndarray) -> bool:
        if frame is None or self.cv2 is None:
            return False
        try:
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            brightness = np.mean(gray)
            if brightness < IMAGE_MIN_BRIGHTNESS:
                return False
                
            sharpness = self.cv2.Laplacian(gray, self.cv2.CV_64F).var()
            if sharpness < IMAGE_MOTION_BLUR_THRESHOLD:
                return False
            return True
        except Exception:
            return False

    def detect_face(self, frame: np.ndarray) -> bool:
        if frame is None or self.face_cascade is None or getattr(self.face_cascade, 'empty', lambda: True)():
            return False
        try:
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
            return len(faces) > 0
        except Exception:
            return False

    def find_best_frame(self, start: float, end: float, num_candidates=5) -> np.ndarray:
        if not self.available:
            return None
            
        duration = max(0.1, end - start)
        step = duration / (num_candidates + 1)
        
        best_frame = None
        best_score = -1.0
        
        midpoint_frame = None
        midpoint_time = start + duration / 2.0
        
        for i in range(1, num_candidates + 1):
            ts = start + i * step
            frame = self.extract_frame(ts)
            
            if frame is None:
                continue
                
            if i == num_candidates // 2 + 1:
                midpoint_frame = frame
                
            if not self.is_good_frame(frame):
                continue
                
            try:
                gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
                sharpness = self.cv2.Laplacian(gray, self.cv2.CV_64F).var()
                if self.detect_face(frame):
                    sharpness *= 1.5
                if sharpness > best_score:
                    best_score = sharpness
                    best_frame = frame
            except Exception:
                pass
                
        if best_frame is not None:
            return best_frame
            
        return midpoint_frame if midpoint_frame is not None else self.extract_frame(midpoint_time)

    def save_frame(self, frame, output_path: Path, quality=95):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        saved = False
        if self.cv2 is not None and frame is not None:
            try:
                is_success, buf = self.cv2.imencode('.png', frame)
                if is_success:
                    output_path.write_bytes(buf.tobytes())
                    saved = True
            except Exception as e:
                logger.warning(f"CV2 imencode PNG failed ({e}), writing fallback image...")

        if not saved:
            # Guaranteed fallback: create clean dark grey PNG using PIL
            try:
                from PIL import Image
                img = Image.new('RGB', (1280, 720), color=(40, 44, 52))
                img.save(output_path, 'PNG')
            except Exception as e2:
                logger.error(f"Failed to save fallback PNG image: {e2}")

    def extract_all_frames(self, state: PipelineState, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        for item in state.active_dialogues():
            frame = self.find_best_frame(item.start, item.end)
            speaker_name = state.get_speaker_safe_name(item.speaker_id)
            fname = f'{item.id_str}_{speaker_name}.png'
            out_path = output_dir / fname
            
            self.save_frame(frame, out_path)
            item.image_path = out_path
            
    def release(self):
        if hasattr(self, 'cap') and self.cap and self.cap.isOpened():
            self.cap.release()
            
    def __del__(self):
        self.release()
