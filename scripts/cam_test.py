"""Quick camera + MediaPipe test. Run on the Latitude."""
import cv2
import mediapipe as mp

cap = cv2.VideoCapture(0)
print("Camera opened:", cap.isOpened())
if cap.isOpened():
    ret, frame = cap.read()
    print("Frame:", ret, frame.shape if ret else "N/A")
    fd = mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    )
    if ret:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = fd.process(rgb)
        n = len(results.detections) if results.detections else 0
        print("Faces:", n)
    fd.close()
    cap.release()
else:
    print("Camera not available")
