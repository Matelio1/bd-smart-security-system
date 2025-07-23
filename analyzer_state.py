import threading
import time
import os
from datetime import datetime

# These will be set by the Flask app at runtime
app = None
db = None
Video = None
Frame = None
DetectedObject = None
RealtimeAnalyzer = None

analyzers_globally_stopped = False

analyzer_threads = {}
analyzer_instances = {}
analyzer_running = {}
analyzer_lock = threading.RLock()
camera_last_access = {}

def set_app_context(flask_app, db_models, analyzer_class):
    """Call this ONCE in app.py after app and models are initialized."""
    global app, db, Video, Frame, DetectedObject, RealtimeAnalyzer
    app = flask_app
    db = db_models['db']
    Video = db_models['Video']
    Frame = db_models['Frame']
    DetectedObject = db_models['DetectedObject']
    RealtimeAnalyzer = analyzer_class

def start_all_camera_analyzers():
    global analyzers_globally_stopped
    if analyzers_globally_stopped:
        app.logger.info("Global stop is active. Not starting any analyzers.")
        return 0, []
    temp_analyzer = None
    started_count = 0
    available_cameras = []
    try:
        app.logger.info("Detecting available cameras to start analyzers...")
        temp_analyzer = RealtimeAnalyzer()
        available_cameras = temp_analyzer.list_cameras()
        app.logger.info(f"Available cameras: {available_cameras}")
        if not available_cameras:
            app.logger.error("No cameras detected! Please check your hardware and permissions.")
        cameras_to_start = available_cameras[:app.config['MAX_CONCURRENT_CAMERAS']]
        if len(available_cameras) > app.config['MAX_CONCURRENT_CAMERAS']:
            app.logger.info(f"Limiting initial startup to {app.config['MAX_CONCURRENT_CAMERAS']} cameras. Others will start on demand.")
        for camera_idx in cameras_to_start:
            app.logger.info(f"Starting analyzer for camera {camera_idx}...")
            if start_analyzer_thread(camera_index=camera_idx, show_video=False):
                started_count += 1
                camera_last_access[camera_idx] = time.time()
            else:
                app.logger.error(f"Failed to start analyzer thread for camera {camera_idx}")
            time.sleep(app.config['CAMERA_STARTUP_DELAY'])
        app.logger.info(f"start_all_camera_analyzers returning: started={started_count}, cameras={available_cameras}")
        return started_count, available_cameras
    except Exception as e:
        app.logger.error(f"Error starting camera analyzers: {str(e)}")
        app.logger.info(f"start_all_camera_analyzers returning (error): started={started_count}, cameras={available_cameras}")
        return started_count, available_cameras
    finally:
        if temp_analyzer:
            try:
                del temp_analyzer
            except Exception:
                pass

def run_analyzer_in_thread(camera_index=0, show_video=False):
    app.logger.info(f"🧵 Analyzer thread started for camera {camera_index}.")
    temp_analyzer_instance = None
    try:
        os.makedirs(app.config['REALTIME_FOLDER'], exist_ok=True)
        with analyzer_lock:
            active_camera_count = sum(1 for cam_idx, running in analyzer_running.items() if running)
        base_frame_rate = app.config['ANALYSIS_CONFIG']["realtime"]["frame_rate"]
        dynamic_frame_rate = base_frame_rate * max(1.0, min(3.0, active_camera_count / 2))
        app.logger.info(f"Camera {camera_index} using dynamic frame rate: {dynamic_frame_rate:.3f}s sleep")

        temp_analyzer_instance = RealtimeAnalyzer(
            model_path=app.config['YOLO_MODEL_PATH'],
            save_folder=app.config['REALTIME_FOLDER'],
            confidence=app.config['ANALYSIS_CONFIG']["realtime"]["confidence"],
            save_interval=app.config['ANALYSIS_CONFIG']["realtime"]["save_interval"],
            include_classes=app.config['ANALYSIS_CONFIG']["realtime"]["include_classes"],
            frame_rate=dynamic_frame_rate
        )
        app.logger.info(f"RealtimeAnalyzer initialized for camera {camera_index}.")

        original_process_frame = temp_analyzer_instance.process_frame

        def process_frame_with_db(frame):
            results, detections = original_process_frame(frame)
            if len(detections) > 0:
                try:
                    with app.app_context():
                        current_cam_index = temp_analyzer_instance.camera_index if temp_analyzer_instance else 'unknown'
                        camera_folder = os.path.join(temp_analyzer_instance.output_folder, f"camera_{current_cam_index}")
                        if os.path.exists(camera_folder):
                            files = sorted([f for f in os.listdir(camera_folder) if os.path.isfile(os.path.join(camera_folder, f))], reverse=True)
                            if files:
                                latest_file = files[0]
                                image_path = os.path.join(camera_folder, latest_file)
                                camera_id = current_cam_index
                                camera_video = Video.query.filter_by(
                                    filename=f"camera_{camera_id}_live"
                                ).first()
                                if not camera_video:
                                    camera_video = Video(
                                        filename=f"camera_{camera_id}_live",
                                        user_id=None,
                                        analysis_result=f"Live feed from camera {camera_id}"
                                    )
                                    db.session.add(camera_video)
                                    db.session.commit()
                                    app.logger.info(f"Created new video record for camera {camera_id}")
                                frame_num = temp_analyzer_instance.frame_count if temp_analyzer_instance else 0
                                frame_record = Frame(
                                    frame_number=frame_num,
                                    image_path=image_path,
                                    video_id=camera_video.id,
                                    object_count=len(detections),
                                    timestamp=datetime.now()
                                )
                                db.session.add(frame_record)
                                db.session.flush()
                                for _, det in detections.iterrows():
                                    obj = DetectedObject(
                                        object_name=det['name'],
                                        object_type=DetectedObject.get_type_code(det['name']),
                                        probability=float(det['confidence']),
                                        frame_id=frame_record.id,
                                        x_min=int(det['xmin']),
                                        y_min=int(det['ymin']),
                                        x_max=int(det['xmax']),
                                        y_max=int(det['ymax'])
                                    )
                                    db.session.add(obj)
                                db.session.commit()
                                app.logger.debug(f"Saved frame {frame_num} for camera {camera_id} to DB.")
                            else:
                                app.logger.warning(f"No files found in {camera_folder} after processing frame.")
                        else:
                            app.logger.warning(f"Camera folder {camera_folder} not found for saving DB record.")
                except Exception as e:
                    app.logger.exception(f"Error saving frame to database: {str(e)}")
                    with app.app_context():
                        db.session.rollback()
            return results, detections

        temp_analyzer_instance.process_frame = process_frame_with_db
        app.logger.info(f"Overrode process_frame method for DB saving for camera {camera_index}.")

        with analyzer_lock:
            analyzer_instances[camera_index] = temp_analyzer_instance
            analyzer_running[camera_index] = True

        app.logger.info(f"Starting analyzer instance loop for camera {camera_index}...")
        start_successful = temp_analyzer_instance.start(camera_index=camera_index, show_video=show_video)

        if not start_successful:
            app.logger.error(f"Analyzer instance start() method returned False for camera {camera_index}.")
        else:
            app.logger.info(f"Analyzer instance start() method completed for camera {camera_index}.")

    except Exception as e:
        app.logger.exception(f"FATAL ERROR in analyzer thread for camera {camera_index}: {str(e)}")
    finally:
        with analyzer_lock:
            analyzer_running[camera_index] = False
            instance = analyzer_instances.get(camera_index)
            if instance is not None:
                try:
                    instance.stop()  # Safe even if already stopped
                except Exception as stop_err:
                    app.logger.error(f"Error during final stop for camera {camera_index}: {stop_err}")
            analyzer_instances[camera_index] = None
        app.logger.info(f"🧵 Analyzer thread finished for camera {camera_index}.")

def start_analyzer_thread(camera_index=0, show_video=False):
    global analyzers_globally_stopped
    if analyzers_globally_stopped:
        app.logger.info(f"Global stop is active. Not starting analyzer for camera {camera_index}.")
        return False
    with analyzer_lock:
        thread_exists = camera_index in analyzer_threads and analyzer_threads[camera_index].is_alive()
        running = camera_index in analyzer_running and analyzer_running[camera_index]
        if thread_exists and running:
            app.logger.warning(f"Analyzer thread for camera {camera_index} is already running")
            return False
    app.logger.info(f"Starting real-time analyzer thread for camera {camera_index}...")
    new_thread = threading.Thread(
        target=run_analyzer_in_thread,
        args=(camera_index, show_video),
        daemon=True
    )
    with analyzer_lock:
        analyzer_threads[camera_index] = new_thread
        analyzer_running[camera_index] = False
    new_thread.start()
    return True

def stop_analyzer_thread(camera_index):
    with analyzer_lock:
        thread = analyzer_threads.get(camera_index)
        running = analyzer_running.get(camera_index, False)
        if running:
            app.logger.info(f"Stopping analyzer thread for camera {camera_index}")
            analyzer_running[camera_index] = False
        else:
            app.logger.info(f"No running analyzer thread for camera {camera_index} to stop")
            thread = None
    # Wait for the thread to finish outside the lock
    if thread is not None and thread.is_alive():
        app.logger.info(f"Waiting for analyzer thread for camera {camera_index} to exit...")
        thread.join(timeout=10)
        app.logger.info(f"Analyzer thread for camera {camera_index} has exited.")
    # Explicitly release the camera resource if instance exists
    with analyzer_lock:
        instance = analyzer_instances.get(camera_index)
        if instance is not None:
            try:
                instance.stop()
                app.logger.info(f"Explicitly called stop() on analyzer instance for camera {camera_index}")
            except Exception as e:
                app.logger.error(f"Error calling stop() on analyzer instance for camera {camera_index}: {e}")
        analyzer_instances[camera_index] = None
def stop_all_analyzers():
    global analyzers_globally_stopped
    analyzers_globally_stopped = True
    stopped = 0
    with analyzer_lock:
        for cam_idx in list(analyzer_running.keys()):
            if analyzer_running[cam_idx]:
                stop_analyzer_thread(cam_idx)
                stopped += 1
    return stopped

def allow_analyzers_start():
    global analyzers_globally_stopped
    analyzers_globally_stopped = False

def check_inactive_cameras():
    app.logger.debug("Checking for inactive cameras")
    current_time = time.time()
    cameras_to_stop = []
    with analyzer_lock:
        active_count = sum(1 for running in analyzer_running.values() if running)
        if active_count <= 2:
            return
        for cam_idx in list(analyzer_running.keys()):
            if analyzer_running[cam_idx] and cam_idx in camera_last_access:
                idle_time = current_time - camera_last_access[cam_idx]
                if idle_time > app.config['INACTIVE_CAMERA_TIMEOUT']:
                    cameras_to_stop.append(cam_idx)
    for cam_idx in cameras_to_stop:
        app.logger.info(f"Stopping inactive camera {cam_idx} after {app.config['INACTIVE_CAMERA_TIMEOUT']}s of inactivity")
        stop_analyzer_thread(cam_idx)