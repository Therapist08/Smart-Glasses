#!/usr/bin/env python3
# ============================================================
#  LAPTOP TEST VERSION — Smart Glasses (WINDOWS - FIXED)
#  Fix 1: Audio uses PowerShell TTS (no pyttsx3 threading bug)
#  Fix 2: Camera display separated from YOLO inference (no lag)
# ============================================================

import sys
import threading
import time
import logging
import queue
import subprocess
import tempfile
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("laptop_test")

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False
    print("❌ OpenCV not found. Run: pip install opencv-python")

try:
    from ultralytics import YOLO
    YOLO_OK = True
except ImportError:
    YOLO_OK = False
    print("❌ ultralytics not found. Run: pip install ultralytics")

try:
    import pytesseract
    import numpy as np
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESS_OK = True
except ImportError:
    TESS_OK = False
    print("❌ pytesseract not found. Run: pip install pytesseract")

import numpy as np

# ─────────────────────────────────────────────────────────────
#  LANGUAGE CONFIG
# ─────────────────────────────────────────────────────────────
LANGUAGES = {
    "english": {"tesseract_lang": "eng",     "label": "English"},
    "hindi":   {"tesseract_lang": "hin+eng", "label": "Hindi"},
    "marathi": {"tesseract_lang": "mar+eng", "label": "Marathi"},
}
LANGUAGE_ORDER = ["english", "hindi", "marathi"]

SCENE_START = {
    "english": "I can see: ",
    "hindi":   "मैं देख रहा हूं: ",
    "marathi": "मला दिसत आहे: ",
}
SCENE_CLEAR = {
    "english": "The area ahead is clear.",
    "hindi":   "आगे का रास्ता साफ है।",
    "marathi": "पुढचा रस्ता मोकळा आहे.",
}

# ─────────────────────────────────────────────────────────────
#  AUDIO — PowerShell TTS (no install needed, works on all Windows)
# ─────────────────────────────────────────────────────────────
import tempfile, os

VBS_PATH = os.path.join(tempfile.gettempdir(), "smart_glasses_tts.vbs")
with open(VBS_PATH, "w") as _f:
    _f.write('Set s = CreateObject("SAPI.SpVoice")\n')
    _f.write('s.Rate = 1\n')
    _f.write('s.Volume = 100\n')
    _f.write('s.Speak WScript.Arguments(0)\n')

# ─────────────────────────────────────────────────────────────
#  AUDIO — Hybrid TTS
#  English  → VBScript SAPI  (offline, instant)
#  Hindi    → Google TTS     (online, natural voice)
#  Marathi  → Google TTS     (online, natural voice)
# ─────────────────────────────────────────────────────────────

# gTTS language codes
GTTS_LANG = {
    "english": None,   # handled by VBScript
    "hindi":   "hi",
    "marathi": "mr",
}

class AudioOutput:
    def __init__(self):
        self._lang_index   = 0
        self._queue        = queue.Queue()
        self._stop_event   = threading.Event()
        self._current_proc = None
        self._lock         = threading.Lock()
        self._pygame_ready = False

        # Initialize pygame mixer for playing gTTS audio
        try:
            import pygame
            pygame.mixer.init()
            self._pygame_ready = True
            print("✅ pygame audio ready")
        except Exception as e:
            print(f"⚠️ pygame not available: {e}")

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        print("✅ Audio engine ready (VBScript for English, gTTS for Hindi/Marathi)")

    @property
    def current_language(self):
        return LANGUAGE_ORDER[self._lang_index]

    def cycle_language(self):
        self._lang_index = (self._lang_index + 1) % len(LANGUAGE_ORDER)
        label = LANGUAGES[self.current_language]["label"]
        print(f"\n🌐 Language changed to: {label}\n")
        self.speak_priority("Language changed to " + label)

    def speak(self, text):
        if text:
            self._queue.put(text)

    def speak_priority(self, text):
        self._kill_current()
        if text:
            self._queue.put(text)

    def stop(self):
        self._stop_event.set()
        self._kill_current()

    def _kill_current(self):
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if self._current_proc and self._current_proc.poll() is None:
                self._current_proc.terminate()
                self._current_proc = None
        # Stop pygame if playing
        try:
            import pygame
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def _say(self, text):
        print(f"\n🔊 [{LANGUAGES[self.current_language]['label']}] {text}\n")
        lang = self.current_language

        if lang == "english":
            self._speak_vbs(text)
        else:
            self._speak_gtts(text, GTTS_LANG[lang])

    def _speak_vbs(self, text):
        """Windows SAPI via VBScript — for English."""
        safe = text.replace('"', '').replace("'", '').replace('\n', ' ').strip()
        if not safe:
            return
        try:
            with self._lock:
                self._current_proc = subprocess.Popen(
                    ["cscript", "//nologo", VBS_PATH, safe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self._current_proc.wait()
        except Exception as e:
            print(f"⚠️ VBS TTS error: {e}")

    def _speak_gtts(self, text, lang_code):
    
        try:
            from gtts import gTTS
            import pygame
            import uuid

            # Generate a unique filename every time — avoids permission conflict
            # because pygame holds the previous file open
            tmp = os.path.join(tempfile.gettempdir(), f"sg_tts_{uuid.uuid4().hex}.mp3")

            tts = gTTS(text=text, lang=lang_code, slow=False)
            tts.save(tmp)

            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()

            # Wait until done playing
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)

            # Stop and unload so file is released before we delete it
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()

            # Clean up the temp file now that it's released
            try:
                os.remove(tmp)
            except Exception:
                pass

        except Exception as e:
            print(f"⚠️ gTTS error (no internet?): {e}")
            print(f"   Text was: {text}")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.3)
                self._say(text)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"⚠️ Worker error: {e}")
# ─────────────────────────────────────────────────────────────
#  WEBCAM — with dedicated display thread (no more lag)
# ─────────────────────────────────────────────────────────────
class WebcamHandler:
    """
    Runs a background thread that continuously reads frames.
    get_frame() always returns the LATEST frame instantly.
    This way the display is smooth and YOLO doesn't block it.
    """
    def __init__(self, index=0):
        self._latest_frame = None
        self._lock         = threading.Lock()
        self._running      = False

        if not CV2_OK:
            self._cap = None
            return

        self._cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            print("❌ Could not open webcam.")
            self._cap = None
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        # Set buffer size to 1 so we always get the latest frame
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._running = True
        self._thread  = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        print("✅ Webcam opened.")

    def _capture_loop(self):
        """Continuously grab frames in background — keeps buffer fresh."""
        while self._running and self._cap:
            ret, frame = self._cap.read()
            if ret:
                with self._lock:
                    self._latest_frame = frame

    def capture_frame(self):
        """Return latest frame instantly — never blocks."""
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def release(self):
        self._running = False
        if self._cap:
            self._cap.release()

# ─────────────────────────────────────────────────────────────
#  LABEL MAP — all 80 COCO classes
# ─────────────────────────────────────────────────────────────
LABEL_MAP = {
    "person":           {"english": "person",           "hindi": "व्यक्ति",          "marathi": "व्यक्ती"},
    "bicycle":          {"english": "bicycle",           "hindi": "साइकिल",           "marathi": "सायकल"},
    "car":              {"english": "car",               "hindi": "कार",              "marathi": "कार"},
    "motorcycle":       {"english": "motorcycle",        "hindi": "मोटरसाइकिल",      "marathi": "मोटारसायकल"},
    "airplane":         {"english": "airplane",          "hindi": "हवाई जहाज",        "marathi": "विमान"},
    "bus":              {"english": "bus",               "hindi": "बस",               "marathi": "बस"},
    "train":            {"english": "train",             "hindi": "ट्रेन",            "marathi": "रेल्वे"},
    "truck":            {"english": "truck",             "hindi": "ट्रक",             "marathi": "ट्रक"},
    "boat":             {"english": "boat",              "hindi": "नाव",              "marathi": "नाव"},
    "traffic light":    {"english": "traffic light",    "hindi": "ट्रैफिक लाइट",    "marathi": "वाहतूक दिवा"},
    "fire hydrant":     {"english": "fire hydrant",     "hindi": "फायर हाइड्रेंट",  "marathi": "अग्निशामक नळ"},
    "stop sign":        {"english": "stop sign",        "hindi": "रुको का संकेत",    "marathi": "थांबा चिन्ह"},
    "parking meter":    {"english": "parking meter",    "hindi": "पार्किंग मीटर",    "marathi": "पार्किंग मीटर"},
    "bench":            {"english": "bench",            "hindi": "बेंच",             "marathi": "बाक"},
    "bird":             {"english": "bird",             "hindi": "पक्षी",            "marathi": "पक्षी"},
    "cat":              {"english": "cat",              "hindi": "बिल्ली",           "marathi": "मांजर"},
    "dog":              {"english": "dog",              "hindi": "कुत्ता",           "marathi": "कुत्रा"},
    "horse":            {"english": "horse",            "hindi": "घोड़ा",            "marathi": "घोडा"},
    "sheep":            {"english": "sheep",            "hindi": "भेड़",             "marathi": "मेंढी"},
    "cow":              {"english": "cow",              "hindi": "गाय",              "marathi": "गाय"},
    "elephant":         {"english": "elephant",         "hindi": "हाथी",             "marathi": "हत्ती"},
    "bear":             {"english": "bear",             "hindi": "भालू",             "marathi": "अस्वल"},
    "zebra":            {"english": "zebra",            "hindi": "ज़ेबरा",           "marathi": "झेब्रा"},
    "giraffe":          {"english": "giraffe",          "hindi": "जिराफ",            "marathi": "जिराफ"},
    "backpack":         {"english": "backpack",         "hindi": "बैग",              "marathi": "पिशवी"},
    "umbrella":         {"english": "umbrella",         "hindi": "छाता",             "marathi": "छत्री"},
    "handbag":          {"english": "handbag",          "hindi": "हैंडबैग",          "marathi": "हॅंडबॅग"},
    "tie":              {"english": "tie",              "hindi": "टाई",              "marathi": "टाय"},
    "suitcase":         {"english": "suitcase",         "hindi": "सूटकेस",           "marathi": "सूटकेस"},
    "frisbee":          {"english": "frisbee",          "hindi": "फ्रिसबी",          "marathi": "फ्रिसबी"},
    "skis":             {"english": "skis",             "hindi": "स्की",             "marathi": "स्की"},
    "snowboard":        {"english": "snowboard",        "hindi": "स्नोबोर्ड",        "marathi": "स्नोबोर्ड"},
    "sports ball":      {"english": "ball",             "hindi": "गेंद",             "marathi": "चेंडू"},
    "kite":             {"english": "kite",             "hindi": "पतंग",             "marathi": "पतंग"},
    "baseball bat":     {"english": "baseball bat",     "hindi": "बेसबॉल बैट",       "marathi": "बेसबॉल बॅट"},
    "baseball glove":   {"english": "baseball glove",   "hindi": "बेसबॉल दस्ताना",  "marathi": "बेसबॉल ग्लोव्ह"},
    "skateboard":       {"english": "skateboard",       "hindi": "स्केटबोर्ड",       "marathi": "स्केटबोर्ड"},
    "surfboard":        {"english": "surfboard",        "hindi": "सर्फबोर्ड",        "marathi": "सर्फबोर्ड"},
    "tennis racket":    {"english": "tennis racket",    "hindi": "टेनिस रैकेट",      "marathi": "टेनिस रॅकेट"},
    "bottle":           {"english": "bottle",           "hindi": "बोतल",             "marathi": "बाटली"},
    "wine glass":       {"english": "wine glass",       "hindi": "गिलास",            "marathi": "ग्लास"},
    "cup":              {"english": "cup",              "hindi": "कप",               "marathi": "कप"},
    "fork":             {"english": "fork",             "hindi": "कांटा",            "marathi": "काटा"},
    "knife":            {"english": "knife",            "hindi": "चाकू",             "marathi": "चाकू"},
    "spoon":            {"english": "spoon",            "hindi": "चम्मच",            "marathi": "चमचा"},
    "bowl":             {"english": "bowl",             "hindi": "कटोरा",            "marathi": "वाटी"},
    "banana":           {"english": "banana",           "hindi": "केला",             "marathi": "केळ"},
    "apple":            {"english": "apple",            "hindi": "सेब",              "marathi": "सफरचंद"},
    "sandwich":         {"english": "sandwich",         "hindi": "सैंडविच",          "marathi": "सँडविच"},
    "orange":           {"english": "orange",           "hindi": "संतरा",            "marathi": "संत्रा"},
    "broccoli":         {"english": "broccoli",         "hindi": "ब्रोकली",          "marathi": "ब्रोकली"},
    "carrot":           {"english": "carrot",           "hindi": "गाजर",             "marathi": "गाजर"},
    "hot dog":          {"english": "hot dog",          "hindi": "हॉट डॉग",          "marathi": "हॉट डॉग"},
    "pizza":            {"english": "pizza",            "hindi": "पिज्जा",           "marathi": "पिझ्झा"},
    "donut":            {"english": "donut",            "hindi": "डोनट",             "marathi": "डोनट"},
    "cake":             {"english": "cake",             "hindi": "केक",              "marathi": "केक"},
    "chair":            {"english": "chair",            "hindi": "कुर्सी",           "marathi": "खुर्ची"},
    "couch":            {"english": "sofa",             "hindi": "सोफा",             "marathi": "सोफा"},
    "potted plant":     {"english": "plant",            "hindi": "पौधा",             "marathi": "झाड"},
    "bed":              {"english": "bed",              "hindi": "बिस्तर",           "marathi": "पलंग"},
    "dining table":     {"english": "table",            "hindi": "मेज",              "marathi": "टेबल"},
    "toilet":           {"english": "toilet",           "hindi": "शौचालय",           "marathi": "शौचालय"},
    "tv":               {"english": "television",       "hindi": "टेलीविजन",         "marathi": "दूरदर्शन"},
    "laptop":           {"english": "laptop",           "hindi": "लैपटॉप",           "marathi": "लॅपटॉप"},
    "mouse":            {"english": "mouse",            "hindi": "माउस",             "marathi": "माउस"},
    "remote":           {"english": "remote control",   "hindi": "रिमोट",            "marathi": "रिमोट"},
    "keyboard":         {"english": "keyboard",         "hindi": "कीबोर्ड",          "marathi": "कीबोर्ड"},
    "cell phone":       {"english": "mobile phone",     "hindi": "मोबाइल फोन",       "marathi": "मोबाईल फोन"},
    "microwave":        {"english": "microwave",        "hindi": "माइक्रोवेव",       "marathi": "मायक्रोवेव्ह"},
    "oven":             {"english": "oven",             "hindi": "ओवन",              "marathi": "ओव्हन"},
    "toaster":          {"english": "toaster",          "hindi": "टोस्टर",           "marathi": "टोस्टर"},
    "sink":             {"english": "sink",             "hindi": "सिंक",             "marathi": "सिंक"},
    "refrigerator":     {"english": "refrigerator",     "hindi": "फ्रिज",            "marathi": "फ्रीज"},
    "book":             {"english": "book",             "hindi": "किताब",            "marathi": "पुस्तक"},
    "clock":            {"english": "clock",            "hindi": "घड़ी",             "marathi": "घड्याळ"},
    "vase":             {"english": "vase",             "hindi": "फूलदान",           "marathi": "फुलदाणी"},
    "scissors":         {"english": "scissors",         "hindi": "कैंची",            "marathi": "कात्री"},
    "teddy bear":       {"english": "teddy bear",       "hindi": "टेडी बेयर",        "marathi": "टेडी बेअर"},
    "hair drier":       {"english": "hair dryer",       "hindi": "हेयर ड्रायर",      "marathi": "हेअर ड्रायर"},
    "toothbrush":       {"english": "toothbrush",       "hindi": "टूथब्रश",          "marathi": "दातांचा ब्रश"},
}

# ─────────────────────────────────────────────────────────────
#  SCENE MODE — YOLO runs in background, display stays smooth
# ─────────────────────────────────────────────────────────────
class SceneMode:
    def __init__(self, camera, audio):
        self._camera   = camera
        self._audio    = audio
        self._model    = None
        self._running  = False

        if YOLO_OK:
            try:
                print("⏳ Loading YOLOv8 model (downloads ~6MB on first run)...")
                self._model = YOLO("yolov8n.pt")
                print("✅ YOLOv8 loaded.")
            except Exception as e:
                logger.error("YOLO load failed: %s", e)

    def start(self):
        self._running = True
        lang = self._audio.current_language
        msgs = {
            "english": "Scene mode active. Describing surroundings every 4 seconds.",
            "hindi":   "दृश्य विवरण मोड सक्रिय।",
            "marathi": "दृश्य वर्णन मोड सुरू.",
        }
        self._audio.speak_priority(msgs[lang])

        # Thread 1 — smooth live camera display (runs fast, no YOLO)
        threading.Thread(target=self._display_loop, daemon=True).start()

        # Thread 2 — YOLO inference every 4 seconds (runs slow, no display)
        threading.Thread(target=self._inference_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _display_loop(self):
        """Just shows camera feed smoothly — no YOLO here."""
        while self._running:
            frame = self._camera.capture_frame()
            if frame is not None:
                cv2.imshow("Smart Glasses — Live Feed  |  Q in terminal to quit", frame)
            cv2.waitKey(30)   # ~30fps display, non-blocking

    def _inference_loop(self):
        """Runs YOLO every 4 seconds on latest frame — no display here."""
        while self._running:
            frame = self._camera.capture_frame()
            if frame is not None:
                desc = self._describe(frame)
                if desc:
                    self._audio.speak(desc)
            # Wait 4 seconds before next detection
            for _ in range(40):
                if not self._running:
                    break
                time.sleep(0.1)

    def _describe(self, frame):
        if self._model is None or frame is None:
            return ""
        results  = self._model(frame, conf=0.45, verbose=False)
        detected = []
        for result in results:
            for box in result.boxes:
                cls  = result.names[int(box.cls[0])].lower()
                size = float(box.xyxy[0][3] - box.xyxy[0][1]) / frame.shape[0]
                detected.append((cls, size))

        lang = self._audio.current_language
        if not detected:
            return SCENE_CLEAR[lang]

        detected.sort(key=lambda x: x[1], reverse=True)
        detected = detected[:5]

        dist_words = {
            "english": ("very close ", "close ", "far away "),
            "hindi":   ("बिल्कुल करीब ", "करीब ", "दूर "),
            "marathi": ("अगदी जवळ ", "जवळ ", "दूर "),
        }[lang]

        and_word = {"english": " and ", "hindi": " और ", "marathi": " आणि "}[lang]
        parts = []
        seen  = set()

        for cls, size in detected:
            if cls in seen:
                continue
            seen.add(cls)
            label = LABEL_MAP.get(cls, {}).get(lang, cls)
            dw    = dist_words[0] if size > 0.5 else (dist_words[1] if size > 0.2 else dist_words[2])
            parts.append(dw + label)

        body = ", ".join(parts[:-1]) + and_word + parts[-1] if len(parts) > 1 else parts[0]
        return SCENE_START[lang] + body + "."

# ─────────────────────────────────────────────────────────────
#  OCR MODE
# ─────────────────────────────────────────────────────────────
class OcrMode:
    def __init__(self, camera, audio):
        self._camera = camera
        self._audio  = audio
        self._busy   = False

    def activate(self):
        lang = self._audio.current_language
        msgs = {
            "english": "OCR mode. Point camera at text and press M to read.",
            "hindi":   "OCR मोड। पाठ की ओर कैमरा करें और M दबाएं।",
            "marathi": "OCR मोड. मजकुरावर कॅमेरा धरा आणि M दाबा.",
        }
        self._audio.speak_priority(msgs[lang])

    def read_now(self):
        if self._busy:
            return
        threading.Thread(target=self._do_ocr, daemon=True).start()

    def _do_ocr(self):
        self._busy = True
        try:
            if not TESS_OK or not CV2_OK:
                self._audio.speak("Tesseract not installed.")
                return

            lang      = self._audio.current_language
            tess_lang = LANGUAGES[lang]["tesseract_lang"]
            reading   = {"english": "Reading...", "hindi": "पढ़ रहा हूं...", "marathi": "वाचत आहे..."}
            self._audio.speak(reading[lang])

            frame = self._camera.capture_frame()
            if frame is None:
                self._audio.speak("Camera error.")
                return

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            gray = cv2.fastNlMeansDenoising(gray, h=10)
            proc = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 10
            )
            cv2.imshow("OCR — What Tesseract Sees", proc)
            cv2.waitKey(1)

            text = pytesseract.image_to_string(
                proc, config=f"--oem 3 --psm 6 -l {tess_lang}"
            ).strip()

            if not text or len(text) < 3:
                no_text = {
                    "english": "No text found. Try better lighting.",
                    "hindi":   "कोई पाठ नहीं मिला।",
                    "marathi": "मजकूर सापडला नाही.",
                }
                self._audio.speak(no_text[lang])
            else:
                lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 1]
                clean = " ".join(lines)
                print(f"\n📄 OCR Result:\n{'─'*40}\n{clean}\n{'─'*40}\n")
                self._audio.speak(clean)

        except Exception as e:
            logger.error("OCR error: %s", e)
            self._audio.speak("OCR failed.")
        finally:
            self._busy = False

# ─────────────────────────────────────────────────────────────
#  SIMULATED DISTANCE SENSOR
# ─────────────────────────────────────────────────────────────
class FakeDistanceSensor:
    def __init__(self, alert_callback):
        self._cb      = alert_callback
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        print("✅ Simulated distance sensor started (fires every 20s)")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(20)
            if self._running:
                self._cb(75.0)

# ─────────────────────────────────────────────────────────────
#  KEYBOARD — Windows
# ─────────────────────────────────────────────────────────────
def get_keypress():
    import msvcrt
    return msvcrt.getwch().lower()

# ─────────────────────────────────────────────────────────────
#  MAIN CONTROLLER
# ─────────────────────────────────────────────────────────────
class LaptopTest:
    def __init__(self):
        self._audio   = AudioOutput()
        self._camera  = WebcamHandler(index=0)
        self._scene   = SceneMode(self._camera, self._audio)
        self._ocr     = OcrMode(self._camera, self._audio)
        self._dist    = FakeDistanceSensor(self._on_distance_alert)
        self._in_ocr  = False
        self._running = True

    def run(self):
        print("\n" + "═"*55)
        print("  SMART GLASSES — LAPTOP TEST  (Windows)")
        print("═"*55)
        print("  M  →  Switch mode  (Scene ↔ OCR / Read text)")
        print("  L  →  Change language (English→Hindi→Marathi)")
        print("  Q  →  Quit")
        print("═"*55 + "\n")

        self._audio.speak("Smart glasses test. Ready.")
        self._dist.start()
        self._scene.start()

        while self._running:
            try:
                key = get_keypress()
                if key == 'm':
                    self._on_mode_press()
                elif key == 'l':
                    self._audio.cycle_language()
                elif key == 'q':
                    self._shutdown()
            except KeyboardInterrupt:
                self._shutdown()
            except Exception as e:
                logger.error("Key error: %s", e)

    def _on_mode_press(self):
        if not self._in_ocr:
            self._scene.stop()
            self._in_ocr = True
            self._ocr.activate()
            print("\n[MODE → OCR]  Point camera at text, press M to read\n")
        else:
            if not self._ocr._busy:
                self._ocr.read_now()
            else:
                self._in_ocr = False
                self._scene  = SceneMode(self._camera, self._audio)
                self._scene.start()
                print("\n[MODE → SCENE]\n")

    def _on_distance_alert(self, dist_cm):
        lang   = self._audio.current_language
        dist_m = dist_cm / 100.0
        alerts = {
            "english": f"Warning! Object {dist_m:.1f} meters ahead.",
            "hindi":   f"चेतावनी! आगे {dist_m:.1f} मीटर पर वस्तु है।",
            "marathi": f"सावधान! {dist_m:.1f} मीटर अंतरावर वस्तू आहे.",
        }
        print(f"\n⚠️  DISTANCE ALERT: {dist_cm:.0f}cm away!\n")
        self._audio.speak_priority(alerts[lang])

    def _shutdown(self):
        print("\n👋 Shutting down...")
        self._running = False
        self._scene.stop()
        self._dist.stop()
        self._audio.stop()
        self._camera.release()
        if CV2_OK:
            cv2.destroyAllWindows()
        sys.exit(0)


if __name__ == "__main__":
    LaptopTest().run()
