import cv2
import torch
import os
import time
import warnings
import json
import logging
from datetime import datetime
from threading import Lock

# --- Module-level logger setup ---
logger = logging.getLogger("analyzer")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - analyzer - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Centralized config import
try:
    from flask import current_app
    def get_config(key, default=None):
        try:
            return current_app.config[key]
        except Exception:
            from config import Config
            return getattr(Config, key, default)
except ImportError:
    from config import Config
    def get_config(key, default=None):
        return getattr(Config, key, default)

class Analyzer:
    """Base class for video analysis functionality using YOLO models."""

    # --- Shared model and lock for all Analyzer instances ---
    _shared_model = None
    _shared_model_path = None
    _model_lock = Lock()

    def __init__(self, output_folder=None, model_path=None, confidence=None, 
                 include_classes=None, exclude_classes=None):
        if model_path is None:
            model_path = get_config('YOLO_MODEL_PATH')
        if output_folder is None:
            output_folder = get_config('OUTPUT_FOLDER')
        if confidence is None:
            confidence = get_config('ANALYSIS_CONFIG')["realtime"]["confidence"]
        if include_classes is None:
            include_classes = get_config('ANALYSIS_CONFIG')["realtime"]["include_classes"]
        self.output_folder = output_folder
        self.model_path = model_path
        self.confidence = confidence
        self.include_classes = include_classes
        self.exclude_classes = exclude_classes
        self.model = None
        os.makedirs(output_folder, exist_ok=True)

    def _load_model(self, from_local=True):
        """Load YOLO model from local repository or GitHub, using a shared model for all analyzers."""
        warnings.filterwarnings("ignore", category=FutureWarning)
        with Analyzer._model_lock:
            if (
                Analyzer._shared_model is not None
                and Analyzer._shared_model_path == self.model_path
            ):
                self.model = Analyzer._shared_model
                self.model.conf = self.confidence
                logger.info(f"Reusing shared model: {self.model_path}")
                return True
            try:
                if from_local and self._check_local_repo():
                    logger.info(f"Loading model from local repository: {self.model_path}")
                    model = torch.hub.load("yolov5", 'custom', path=self.model_path, 
                                            source='local', trust_repo=True)
                else:
                    logger.info(f"Loading model from GitHub: {self.model_path}")
                    model = torch.hub.load("ultralytics/yolov5", 'custom', 
                                            path=self.model_path, trust_repo=True)
                model.conf = self.confidence
                Analyzer._shared_model = model
                Analyzer._shared_model_path = self.model_path
                self.model = model
                logger.info(f"✅ Model loaded successfully: {self.model_path}")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to load model: {str(e)}")
                if from_local:
                    logger.info("Attempting to load from GitHub instead...")
                    return self._load_model(from_local=False)
                return False

    def _check_local_repo(self):
        """Check if YOLOv5 repository is available locally."""
        try:
            yolo_dir = os.path.join(os.path.dirname(__file__), "yolov5")
            return os.path.isdir(yolo_dir) and os.path.isfile(os.path.join(yolo_dir, "models", "common.py"))
        except Exception as e:
            logger.error(f"Error checking YOLOv5 repo: {str(e)}")
            return False

    def process_detections(self, frame, detections):
        """Process detection results and annotate the frame with detailed information."""
        annotated_frame = frame.copy()
        detection_results = {}
        h, w = frame.shape[:2]
        cv2.rectangle(annotated_frame, (0, 0), (w, 30), (0, 0, 0), -1)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        processing_info = f"Timestamp: {timestamp} | Objects: {len(detections)}"
        cv2.putText(annotated_frame, processing_info, (10, 20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        class_counts = {}
        for _, det in detections.iterrows():
            obj_name = det['name']
            class_counts[obj_name] = class_counts.get(obj_name, 0) + 1
            if obj_name not in detection_results:
                detection_results[obj_name] = []
            detection_results[obj_name].append(float(det['confidence']))
            xmin, ymin, xmax, ymax = int(det['xmin']), int(det['ymin']), int(det['xmax']), int(det['ymax'])
            label = f"{obj_name} {det['confidence']:.2f}"
            cv2.rectangle(annotated_frame, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
            cv2.putText(annotated_frame, label, (xmin, ymin - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            obj_width = xmax - xmin
            obj_height = ymax - ymin
            size_info = f"W:{obj_width} H:{obj_height}"
            cv2.putText(annotated_frame, size_info, (xmin, ymax + 15), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
        summary_text = " | ".join([f"{cls}: {count}" for cls, count in class_counts.items()])
        cv2.rectangle(annotated_frame, (0, h-30), (w, h), (0, 0, 0), -1)
        cv2.putText(annotated_frame, summary_text, (10, h-10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return annotated_frame, detection_results

    def filter_detections(self, detections):
        """Filter detections based on include/exclude classes."""
        if self.include_classes:
            detections = detections[detections['name'].isin(self.include_classes)]
        if self.exclude_classes:
            detections = detections[~detections['name'].isin(self.exclude_classes)]
        return detections

    def detect_objects(self, frame):
        """Run object detection on a single frame with performance metrics."""
        if self.model is None:
            if not self._load_model():
                return None, None
        try:
            start_time = time.time()
            results = self.model(frame)
            detections = results.pandas().xyxy[0]
            filtered_detections = self.filter_detections(detections)
            processing_time = time.time() - start_time
            logger.info(f"Frame processed in {processing_time:.3f}s | Found {len(filtered_detections)} objects")
            if hasattr(results, 'speed'):
                preprocess_time = results.speed['preprocess']
                inference_time = results.speed['inference']
                postprocess_time = results.speed['postprocess']
                logger.info(f"Performance: Pre={preprocess_time:.1f}ms, Infer={inference_time:.1f}ms, Post={postprocess_time:.1f}ms")
            return results, filtered_detections
        except Exception as e:
            logger.error(f"Error detecting objects: {str(e)}")
            return None, None

class VideoAnalyzer(Analyzer):
    """Analyze pre-recorded videos for object detection."""
    def __init__(self, video_path, output_folder=None, yolo_model_path=None,
                 confidence=None, include_classes=None, exclude_classes=None):
        if yolo_model_path is None:
            yolo_model_path = get_config('YOLO_MODEL_PATH')
        if output_folder is None:
            output_folder = get_config('OUTPUT_FOLDER')
        super().__init__(output_folder, yolo_model_path, confidence, include_classes, exclude_classes)
        self.video_path = video_path

    def extract_frames(self, frame_interval=5):
        if not os.path.exists(self.video_path):
            logger.error(f"Error: Video file not found at {self.video_path}")
            return None
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            logger.error(f"Error: Could not open video file {self.video_path}")
            return None
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.info(f"Video: {self.video_path} | FPS: {fps}, Total frames: {total_frames}")
        extracted_frames = []
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % frame_interval == 0:
                extracted_frames.append(frame)
            frame_count += 1
        cap.release()
        logger.info(f"Extracted {len(extracted_frames)} frames from {total_frames} total frames")
        return extracted_frames

    def detect_activity_with_yolo(self, frames, min_objects=1):
        logger.debug(f"Starting detect_activity_with_yolo with {len(frames)} frames, min_objects={min_objects}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        analysis_folder = os.path.join(self.output_folder, f"activity_{timestamp}")
        activity_frames_folder = os.path.join(analysis_folder, "activity_frames")
        os.makedirs(activity_frames_folder, exist_ok=True)
        if not self._load_model():
            logger.debug("Failed to load model, aborting detection")
            return None
        logger.debug(f"Model loaded successfully with confidence={self.confidence}")
        frames_with_activity = 0
        activity_summary = {}
        activity_details = {}
        failed_frames = 0
        for i, frame in enumerate(frames):
            try:
                print(f"\rProcessing frame {i+1}/{len(frames)} ({(i+1)/len(frames)*100:.1f}%)", end="")
                frame_start = time.time()
                results, detections = self.detect_objects(frame)
                detection_time = time.time() - frame_start
                if results is not None:
                    classes_found = detections['name'].unique().tolist() if len(detections) > 0 else []
                    print(f"\nFrame {i+1}: {len(detections)} objects {classes_found} in {detection_time:.3f}s")
                if len(detections) < min_objects:
                    continue
                frames_with_activity += 1
                frame_filename = os.path.join(activity_frames_folder, f"activity_{i:06d}.jpg")
                annotated_frame, frame_detections = self.process_detections(frame, detections)
                for obj_name, confidences in frame_detections.items():
                    activity_summary[obj_name] = activity_summary.get(obj_name, 0) + len(confidences)
                activity_details[f"activity_{i:06d}.jpg"] = frame_detections
                cv2.imwrite(frame_filename, annotated_frame)
            except Exception as e:
                failed_frames += 1
                logger.error(f"Error processing frame {i}: {str(e)}")
                if failed_frames >= 10:
                    logger.error("Stopping due to too many failures")
                    break
            if (i + 1) % 20 == 0 or i == len(frames) - 1:
                logger.info(f"Analyzed {i + 1}/{len(frames)} frames, found {frames_with_activity} with activity")
        if frames_with_activity == 0:
            logger.info("No activity detected")
            return analysis_folder
        self._save_analysis_summary(analysis_folder, timestamp, frames_with_activity, 
                                   len(frames), failed_frames, activity_summary, activity_details)
        logger.info(f"Activity detection complete. Found {frames_with_activity} frames with activity")
        return analysis_folder, activity_details

    def _save_analysis_summary(self, folder, timestamp, frames_with_activity, 
                              total_frames, failed_frames, activity_summary, activity_details):
        with open(os.path.join(folder, "activity_summary.txt"), 'w') as f:
            f.write(f"Analysis timestamp: {timestamp}\n")
            f.write(f"Total frames analyzed: {total_frames - failed_frames}\n")
            f.write(f"Frames with activity: {frames_with_activity}\n\n")
            f.write("Detected objects summary:\n")
            for obj_name, count in sorted(activity_summary.items(), key=lambda x: x[1], reverse=True):
                f.write(f"- {obj_name}: {count}\n")
        with open(os.path.join(folder, "activity_details.json"), 'w') as f:
            json.dump(activity_details, f, indent=2)

    def analyze_video(self, frame_interval=5, min_objects=1, confidence=None, include_classes=None):
        frames = self.extract_frames(frame_interval=frame_interval)
        if not frames:
            logger.error("Pipeline stopped due to video file error")
            return None
        if confidence is not None:
            self.confidence = confidence
            if self.model:
                self.model.conf = confidence
                logger.info(f"Updated model confidence to {confidence}")
        if include_classes is not None:
            self.include_classes = include_classes
            logger.info(f"Updated include_classes to {include_classes}")
        try:
            result = self.detect_activity_with_yolo(frames, min_objects)
            if result:
                analysis_folder = result[0] if isinstance(result, tuple) else result
                logger.info(f"Process complete. Results in {analysis_folder}")
                return result
            else:
                logger.error("Activity detection failed")
                return None
        except Exception as e:
            logger.error(f"Error analyzing video: {e}")
            return None

class RealtimeAnalyzer(Analyzer):
    """Real-time camera feed analyzer for object detection."""

    def __init__(self, model_path=None, save_folder=None, 
                 confidence=None, save_interval=None, include_classes=None, exclude_classes=None,
                 frame_rate=None):
        if model_path is None:
            model_path = get_config('YOLO_MODEL_PATH')
        if save_folder is None:
            save_folder = get_config('REALTIME_FOLDER')
        if confidence is None:
            confidence = get_config('ANALYSIS_CONFIG')["realtime"]["confidence"]
        if save_interval is None:
            save_interval = get_config('ANALYSIS_CONFIG')["realtime"]["save_interval"]
        if include_classes is None:
            include_classes = get_config('ANALYSIS_CONFIG')["realtime"]["include_classes"]
        if frame_rate is None:
            frame_rate = get_config('ANALYSIS_CONFIG')["realtime"]["frame_rate"]
        super().__init__(save_folder, model_path, confidence, include_classes, exclude_classes)
        self.save_interval = save_interval
        self.camera_index = 0
        self.cap = None
        self.frame_count = 0
        self.current_backend = None
        self.last_error_time = 0
        self.error_cooldown = 5
        self.current_frame = None
        self._should_stop = False
        self.frame_rate = frame_rate
        self._load_model()

    def try_open_camera(self, camera_index, max_attempts=3, backend=None):
        backend_name = f"Backend {backend}" if backend is not None else "Default Backend"
        logger.info(f"Attempting to open camera {camera_index} with {backend_name}...")
        for attempt in range(max_attempts):
            logger.info(f"  Attempt {attempt + 1}/{max_attempts}...")
            cap = None
            try:
                if backend is not None:
                    cap = cv2.VideoCapture(camera_index, backend)
                    self.current_backend = backend
                else:
                    cap = cv2.VideoCapture(camera_index)
                    self.current_backend = None
                if cap and cap.isOpened():
                    logger.info(f"    Camera {camera_index} opened. Checking frame read...")
                    ret, test_frame = cap.read()
                    if ret:
                        logger.info(f"    ✅ Successfully read test frame from camera {camera_index}")
                        return cap
                    else:
                        logger.warning(f"    ⚠️ Opened camera {camera_index}, but failed to read frame")
                        if cap: cap.release()
                else:
                    logger.warning(f"    ❌ Failed to open camera {camera_index} on attempt {attempt + 1}")
            except Exception as e:
                logger.error(f"    ❌ Exception opening camera {camera_index}: {str(e)}")
                if cap: cap.release()
            time.sleep(1)
        logger.error(f"❌ Failed to open camera {camera_index} after {max_attempts} attempts")
        return None

    def list_cameras(self, max_devices=5):
        available_cameras = []
        logger.info(f"🔍 Listing available cameras (checking indices 0 to {max_devices-1})...")
        for index in range(max_devices):
            cap = None
            try:
                cap = cv2.VideoCapture(index)
                if cap and cap.isOpened():
                    available_cameras.append(index)
                    logger.info(f"  ✅ Found camera at index {index}")
                if cap: cap.release()
            except Exception as e:
                logger.warning(f"  ⚠️ Exception checking camera index {index}: {str(e)}")
                if cap: cap.release()
        logger.info(f"📷 Available camera indices found: {available_cameras}")
        return available_cameras

    def select_camera(self, camera_index=None):
        logger.info(f"🔄 Selecting camera. Requested index: {camera_index}")
        available_cameras = self.list_cameras()
        if camera_index is not None:
            try:
                self.camera_index = int(camera_index)
            except (ValueError, TypeError):
                logger.error(f"❌ Invalid camera index provided: {camera_index}. Falling back.")
                self.camera_index = available_cameras[0] if available_cameras else 0
        elif available_cameras:
            self.camera_index = available_cameras[0]
            logger.info(f"ℹ️ No specific camera requested, selecting first available: {self.camera_index}")
        else:
            self.camera_index = 0
            logger.warning("⚠️ No cameras detected, attempting index 0 by default")
        if self.cap:
            logger.info(f"Releasing existing camera capture...")
            self.cap.release()
            self.cap = None
            time.sleep(2)  # <-- Longer delay for RPi4
        # Use only V4L2 and Default backend on RPi/Linux
        backends = [
            (cv2.CAP_V4L2, "V4L2"),
            (None, "Default"),
        ]
        for backend, name in backends:
            logger.info(f"Trying to open camera {self.camera_index} with {name} backend...")
            self.cap = self.try_open_camera(self.camera_index, backend=backend, max_attempts=3)
            if self.cap:
                return True
        logger.error(f"❌❌ Failed to open camera {self.camera_index} with any backend")
        self.cap = None
        return False

    def reconnect_camera(self):
        logger.warning(f"⚠️ Camera {self.camera_index} disconnected. Attempting reconnect...")
        if self.cap:
            self.cap.release()
            self.cap = None
            time.sleep(2)  # <-- Delay for RPi4
        if self.select_camera(self.camera_index):
            logger.info(f"✅ Reconnected to camera {self.camera_index}")
            return True
        else:
            logger.error(f"❌ Failed to reconnect camera {self.camera_index}")
            return False

    def get_current_frame(self):
        return self.current_frame

    def start(self, camera_index=0, show_video=True):
        self._should_stop = False
        logger.info(f"Attempting to start analyzer with camera index: {camera_index}")
        if not self.select_camera(camera_index):
            logger.error(f"Failed to select/open camera {camera_index}. Analyzer cannot start.")
            return False
        logger.info(f"📹 Starting real-time detection loop for camera {self.camera_index}...")
        logger.info(f"📹 Using frame rate of {self.frame_rate}s sleep between frames")
        self.frame_count = 0
        self.current_frame = None
        fail_count = 0
        while not self._should_stop:
            try:
                if not self.cap or not self.cap.isOpened():
                    if self._should_stop:
                        break
                    if not self.reconnect_camera():
                        break
                    time.sleep(1)
                    continue
                ret, frame = self.cap.read()
                if self._should_stop:
                    break
                if not ret or frame is None:
                    fail_count += 1
                    logger.warning(f"⚠️ Failed to read frame from camera {self.camera_index}. Retrying... (fail_count={fail_count})")
                    if self.cap:
                        logger.warning(f"Camera {self.camera_index} isOpened: {self.cap.isOpened()}")
                    else:
                        logger.warning(f"Camera {self.camera_index} cap object is None!")
                    if fail_count > 10:
                        logger.warning(f"Too many failed reads, attempting to reconnect camera {self.camera_index}")
                        self.reconnect_camera()
                        fail_count = 0
                    time.sleep(0.1)
                    continue
                else:
                    fail_count = 0
                self.current_frame = frame.copy()
                self.frame_count += 1
                if self.frame_count % self.save_interval == 0:
                    self.process_frame(frame)
                if show_video:
                    cv2.imshow(f'Live Feed (Cam {self.camera_index} - press q to quit)', self.current_frame)
                    if cv2.waitKey(10) & 0xFF == ord('q'):
                        break
                time.sleep(self.frame_rate)
            except Exception as e:
                logger.exception(f"⚠️ Unhandled exception in analysis loop: {e}")
                time.sleep(1)
        self.stop()
        return True

    def process_frame(self, frame):
        start_time = time.time()
        h, w = frame.shape[:2]
        frame_size = f"{w}x{h}"
        results, detections = self.detect_objects(frame)
        detection_time = time.time() - start_time
        if results is None or len(detections) == 0:
            processing_info = f"No objects detected | Frame: {self.frame_count} | Size: {frame_size} | Time: {detection_time:.3f}s"
            logger.info(processing_info)
            info_frame = frame.copy()
            cv2.putText(info_frame, processing_info, (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            self.current_frame = info_frame
            return results, detections
        annotated_frame, detection_dict = self.process_detections(frame, detections)
        detection_classes = list(detection_dict.keys())
        total_objects = sum(len(confidences) for confidences in detection_dict.values())
        class_counts = {cls: len(confidences) for cls, confidences in detection_dict.items()}
        avg_confidences = {cls: sum(confidences)/len(confidences) for cls, confidences in detection_dict.items()}
        print(f"\n---- Frame {self.frame_count} Analysis ----")
        print(f"Size: {frame_size} | Processing time: {detection_time:.3f}s")
        print(f"Detected {total_objects} objects across {len(detection_classes)} classes:")
        for cls in detection_classes:
            print(f"  - {cls}: {class_counts[cls]} objects (avg conf: {avg_confidences[cls]:.2f})")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        camera_folder = os.path.join(self.output_folder, f"camera_{self.camera_index}")
        os.makedirs(camera_folder, exist_ok=True)
        save_path = os.path.join(camera_folder, f"frame_{timestamp}.jpg")
        try:
            cv2.imwrite(save_path, annotated_frame)
            logger.debug(f"Saved frame to {save_path}")
        except Exception as e:
            logger.error(f"Error saving frame to {save_path}: {str(e)}")
        self.current_frame = annotated_frame
        return results, detections

    def stop(self):
        self._should_stop = True
        if hasattr(self, 'cap') and self.cap is not None:
            try:
                if self.cap.isOpened():
                    logger.info(f"Releasing camera {self.camera_index} in stop()...")
                    self.cap.release()
                else:
                    logger.info(f"Camera {self.camera_index} cap exists but is not opened.")
            except Exception as e:
                logger.error(f"Exception during cap.release(): {e}")
            self.cap = None
            time.sleep(2)  # <-- Delay for RPi4
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        logger.info("Analyzer stopped")

    def reset(self):
        logger.info(f"🔄 Resetting analyzer state for camera {self.camera_index}...")
        self.frame_count = 0
        self.current_frame = None
        self.last_error_time = 0
        return True

# Example usage (optional, can be removed in production)
if __name__ == '__main__':
    print("\n=== Example 1: Analyzing a pre-recorded video ===")
    video_analyzer = VideoAnalyzer(
        video_path="static/videos/test.mp4", 
        output_folder=None,
        yolo_model_path=None,
        confidence=None,
        include_classes=None
    )
    video_analyzer.analyze_video(frame_interval=5, min_objects=1)
    print("\n=== Example 2: Real-time analysis from webcam ===")
    realtime_analyzer = RealtimeAnalyzer(
        confidence=None,
        include_classes=None
    )
    realtime_analyzer.start(camera_index=0, show_video=True)
