from ultralytics import YOLO
import cv2
import pyttsx3
import time

# Initialize Text-to-Speech engine
engine = pyttsx3.init()
engine.setProperty("rate", 150)  # Adjust speed (Lower = slower, Higher = faster)
engine.setProperty("volume", 1.0)  # Adjust volume (1.0 = max)

# Load the YOLOv8 model
model = YOLO("yolov8n.pt")  # Use 'yolov8n.pt' for Raspberry Pi

# Open the IP camera feed
cap = cv2.VideoCapture("http://192.168.0.104:8080/video")

# Keep track of the last spoken object to avoid repetition
last_spoken = ""
last_speak_time = time.time()

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # Run YOLOv8 detection
    results = model(frame)

    # Extract detected object names
    detected_objects = set()  # Use set to avoid duplicates
    for result in results:
        for box in result.boxes:
            class_id = int(box.cls[0])
            label = model.names[class_id]
            detected_objects.add(label)

    # Convert detected objects to a spoken sentence
    if detected_objects:
        detected_sentence = ", ".join(detected_objects)
        
        # Speak only if the object has changed or 5 seconds have passed
        if detected_sentence != last_spoken or (time.time() - last_speak_time > 5):
            text_to_speak = f"I see {detected_sentence}."
            engine.say(text_to_speak)
            engine.runAndWait()
            last_spoken = detected_sentence
            last_speak_time = time.time()

    print("Detected objects:", detected_objects)

    # Show the output frame with bounding boxes
    for r in results:
        frame = r.plot()
    cv2.imshow("YOLOv8 Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
