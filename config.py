import os
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-goes-here')
    MAX_CONCURRENT_CAMERAS = int(os.environ.get('MAX_CONCURRENT_CAMERAS', 3))
    CAMERA_STARTUP_DELAY = float(os.environ.get('CAMERA_STARTUP_DELAY', 1.5))
    INACTIVE_CAMERA_TIMEOUT = int(os.environ.get('INACTIVE_CAMERA_TIMEOUT', 300))
    FILE_RETENTION_DAYS = int(os.environ.get('FILE_RETENTION_DAYS', 2)) # Added

    # Paths
    VIDEOS_FOLDER = os.environ.get('VIDEOS_FOLDER', "static/videos")
    OUTPUT_FOLDER = os.environ.get('OUTPUT_FOLDER', "static/output")
    REALTIME_FOLDER = os.environ.get('REALTIME_FOLDER', "static/output/realtime_activity")
    YOLO_MODEL_PATH = os.environ.get('YOLO_MODEL_PATH', "yolov5n.pt")

    # Analysis settings
    ANALYSIS_CONFIG = {
        "realtime": {
            "confidence": float(os.environ.get('REALTIME_CONFIDENCE', 0.5)),
            "save_interval": int(os.environ.get('REALTIME_SAVE_INTERVAL', 20)),
            "frame_rate": float(os.environ.get('REALTIME_FRAME_RATE', 0.2)),
            "include_classes": os.environ.get('REALTIME_INCLUDE_CLASSES', "person,car,truck,motorcycle,bicycle,bus").split(",")
        },
        "video": {
            "confidence": float(os.environ.get('VIDEO_CONFIDENCE', 0.6)),
            "frame_interval": int(os.environ.get('VIDEO_FRAME_INTERVAL', 10)),
            "min_objects": int(os.environ.get('VIDEO_MIN_OBJECTS', 1)),
            "include_classes": os.environ.get('VIDEO_INCLUDE_CLASSES', "person,car,truck").split(",")
        }
    }