"""Quick camera + MediaPipe test. Run on the Latitude."""
import os
from pathlib import Path

import cv2
import httpx
import mediapipe as mp

MODEL_DIR = Path("data/models")
MODEL_FILE = MODEL_DIR / "blaze_face_short_range.tflite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_detector/blaze_face_short_range/float16/latest/"
    "blaze_face_short_range.tflite"
)

# Download model if needed
if not MODEL_FILE.exists():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading face detection model...")
    resp = httpx.get(MODEL_URL, follow_redirects=True)
    MODEL_FILE.write_bytes(resp.content)
    print(f"Saved ({len(resp.content)} bytes)")

# Open camera
cap = cv2.VideoCapture(0)
print("Camera opened:", cap.isOpened())
if not cap.isOpened():
    print("Camera not available")
    raise SystemExit(1)

ret, frame = cap.read()
print("Frame:", ret, frame.shape if ret else "N/A")

if ret:
    # Compute ambient light
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    print(f"Ambient lux: {gray.mean():.0f} / 255")

    # Run face detection (Tasks API)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    options = mp.tasks.vision.FaceDetectorOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_FILE)),
        min_detection_confidence=0.5,
    )
    detector = mp.tasks.vision.FaceDetector.create_from_options(options)
    results = detector.detect(mp_image)

    if results.detections:
        for det in results.detections:
            score = det.categories[0].score
            print(f"Face detected: {score:.1%} confidence")
    else:
        print("No face detected")

    detector.close()

cap.release()
print("Done")
