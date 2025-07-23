from flask import (
    Blueprint, render_template, request, jsonify, redirect, url_for, flash,
    send_from_directory, Response, current_app
)
from flask_login import (
    current_user, login_user, logout_user, login_required
)
from db_models import db, Video, User, Frame, DetectedObject
from forms import LoginForm, RegistrationForm
import os
import json
import time
import cv2
from datetime import datetime
from analyzer import VideoAnalyzer, RealtimeAnalyzer
import threading
import traceback
import numpy as np
import sys
from flask import stream_with_context

# Import analyzer state and logic from analyzer_state.py (NOT app.py)
from analyzer_state import (
    analyzer_threads, analyzer_instances, analyzer_running,
    analyzer_lock, camera_last_access, start_analyzer_thread, stop_analyzer_thread,
    check_inactive_cameras, start_all_camera_analyzers,
    stop_all_analyzers, allow_analyzers_start
)

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('main.index'))
        else:
            flash('Invalid username or password', 'error')
    return render_template('login.html', form=form)

@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('main.login'))
    return render_template('register.html', form=form)

@main_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

@main_bp.route('/analyze', methods=['GET', 'POST'])
@login_required
def analyze_video():
    if request.method == 'POST':
        try:
            if 'video' in request.files:
                file = request.files['video']
                if file.filename != '':
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{timestamp}_{os.path.splitext(file.filename)[0]}.mp4"
                    os.makedirs(current_app.config['VIDEOS_FOLDER'], exist_ok=True)
                    video_path = os.path.join(current_app.config['VIDEOS_FOLDER'], filename)
                    file.save(video_path)
                    video = Video(
                        filename=filename,
                        user_id=current_user.id
                    )
                    db.session.add(video)
                    db.session.commit()
                    analyzer = VideoAnalyzer(
                        video_path=video_path, 
                        output_folder=current_app.config['OUTPUT_FOLDER'],
                        yolo_model_path=current_app.config['YOLO_MODEL_PATH']
                    )
                    analysis_config = current_app.config['ANALYSIS_CONFIG']
                    result = analyzer.analyze_video(
                        frame_interval=analysis_config["video"]["frame_interval"],
                        min_objects=analysis_config["video"]["min_objects"],
                        confidence=analysis_config["video"]["confidence"],
                        include_classes=analysis_config["video"]["include_classes"],
                    )
                    if result and len(result) == 2:
                        analysis_folder, activity_details = result
                        summary_path = os.path.join(analysis_folder, "activity_summary.txt")
                        if os.path.exists(summary_path):
                            with open(summary_path, 'r') as f:
                                video.analysis_result = f.read().strip()
                                db.session.commit()
                        for filename, frame_data in activity_details.items():
                            try:
                                frame_number = int(filename.split('_')[1].split('.')[0])
                            except (IndexError, ValueError):
                                frame_number = 0
                            frame = Frame(
                                frame_number=frame_number,
                                image_path=os.path.join(analysis_folder, "activity_frames", filename),
                                video_id=video.id,
                                object_count=sum(len(confidences) for confidences in frame_data.values())
                            )
                            db.session.add(frame)
                            db.session.flush()
                            for obj_name, confidences in frame_data.items():
                                for confidence in confidences:
                                    obj = DetectedObject(
                                        object_name=obj_name,
                                        object_type=DetectedObject.get_type_code(obj_name),
                                        probability=confidence,
                                        frame_id=frame.id
                                    )
                                    db.session.add(obj)
                            db.session.commit()
                        return jsonify({
                            "status": "success",
                            "message": "Video analyzed and results stored in database",
                            "video_id": video.id
                        })
                    else:
                        return jsonify({
                            "status": "error",
                            "message": "Video analysis failed",
                            "video_id": video.id
                        })
                return jsonify({"status": "error", "message": "Empty video file"})
            return jsonify({"status": "error", "message": "No video file provided"})
        except Exception as e:
            current_app.logger.error(f"Error analyzing video: {e}")
            return jsonify({"status": "error", "message": f"Exception: {str(e)}"}), 500
    else:
        return render_template('analyze.html')

@main_bp.route('/videos', methods=['GET'])
@login_required
def list_videos():
    user_videos = Video.query.filter_by(user_id=current_user.id).all()
    camera_videos = Video.query.filter(
        Video.filename.like("camera_%_live")
    ).all()
    all_videos = user_videos.copy()
    for camera_video in camera_videos:
        if camera_video not in all_videos:
            all_videos.append(camera_video)
    return render_template('videos.html', videos=all_videos)

@main_bp.route('/api/cameras')
def list_cameras():
    try:
        current_app.logger.info("API Request: /api/cameras")
        with analyzer_lock:
            available_cameras = [
                idx for idx, running in analyzer_running.items()
                if running and analyzer_instances.get(idx) is not None
            ]
        current_app.logger.info(f"Available cameras (from running analyzers): {available_cameras}")
        camera_list = []
        for idx in available_cameras:
            camera_list.append({
                "index": idx,
                "name": f"Camera {idx}"
            })
        return jsonify({
            "status": "success",
            "cameras": camera_list
        })
    except Exception as e:
        current_app.logger.error(f"Exception in /api/cameras: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/api/video/<int:video_id>/analysis', methods=['GET'])
@login_required
def get_video_analysis(video_id):
    try:
        video = Video.query.get(video_id)
        if not video or (video.user_id is not None and video.user_id != current_user.id):
            return jsonify({"status": "error", "message": "Video not found or access denied"}), 404
        frames = Frame.query.filter_by(video_id=video.id).all()
        all_objects = {}
        frame_data = []
        for frame in frames:
            objects = DetectedObject.query.filter_by(frame_id=frame.id).all()
            for obj in objects:
                if obj.object_name not in all_objects:
                    all_objects[obj.object_name] = 0
                all_objects[obj.object_name] += 1
            object_names = list(set(obj.object_name for obj in objects))
            frame_data.append({
                "frame_number": frame.frame_number,
                "image_path": frame.image_path.replace('\\', '/') if frame.image_path else None,
                "objects": object_names
            })
        object_list = [{"name": name, "count": count} for name, count in all_objects.items()]
        object_list.sort(key=lambda x: x["count"], reverse=True)
        return jsonify({
            "status": "success",
            "summary": video.analysis_result,
            "objects": object_list,
            "frames": frame_data,
            "video_id": video.id
        })
    except Exception as e:
        current_app.logger.error(f"Exception in get_video_analysis: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/api/video/<int:video_id>/frames', methods=['GET'])
@login_required
def get_video_frames(video_id):
    try:
        current_app.logger.debug(f"Fetching frames for video ID: {video_id}")
        video = Video.query.get(video_id)
        if not video or (video.user_id is not None and video.user_id != current_user.id):
            current_app.logger.warning(f"Video not found or access denied for video ID: {video_id}")
            return jsonify({"status": "error", "message": "Video not found or access denied"}), 404
        frames = Frame.query.filter_by(video_id=video.id).order_by(Frame.frame_number).all()
        current_app.logger.debug(f"Found {len(frames)} frames for video ID: {video_id}")
        frame_data = []
        for frame in frames:
            objects = DetectedObject.query.filter_by(frame_id=frame.id).all()
            object_names = list(set(obj.object_name for obj in objects))
            image_path = f"/api/frame-image/{frame.id}"
            raw_path = frame.image_path.replace('\\', '/') if frame.image_path else None
            frame_data.append({
                "id": frame.id,
                "frame_number": frame.frame_number,
                "timestamp": frame.timestamp,
                "image_path": image_path,
                "raw_path": raw_path,
                "objects": object_names,
                "object_count": len(object_names)
            })
        current_app.logger.debug(f"Returning data for {len(frame_data)} frames")
        return jsonify({
            "status": "success",
            "video_id": video_id,
            "frames": frame_data,
            "frame_count": len(frame_data)
        })
    except Exception as e:
        current_app.logger.error(f"Exception in get_video_frames: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/api/frame-image/<int:frame_id>', methods=['GET'])
@login_required
def get_frame_image(frame_id):
    try:
        current_app.logger.debug(f"Request for frame image ID: {frame_id}")
        frame = Frame.query.get(frame_id)
        if not frame:
            current_app.logger.warning(f"Frame not found: {frame_id}")
            return jsonify({"status": "error", "message": "Frame not found"}), 404
        video = Video.query.get(frame.video_id)
        if not video or (video.user_id is not None and video.user_id != current_user.id):
            current_app.logger.warning(f"Access denied for frame ID: {frame_id}")
            return jsonify({"status": "error", "message": "Access denied"}), 403
        if not frame.image_path:
            current_app.logger.error(f"Image path not found in database for frame ID: {frame_id}")
            return jsonify({"status": "error", "message": "Image path not found in database"}), 404
        normalized_path = os.path.normpath(frame.image_path).replace('\\', '/')
        if not os.path.exists(normalized_path):
            current_app.logger.error(f"Image file not found: {normalized_path}")
            return jsonify({"status": "error", "message": "Image file not found on server"}), 404
        try:
            directory = os.path.dirname(normalized_path)
            filename = os.path.basename(normalized_path)
            current_app.logger.debug(f"Serving image from directory: {directory}, filename: {filename}")
            response = send_from_directory(directory, filename)
            return response
        except Exception as e:
            current_app.logger.error(f"Error serving image: {str(e)}")
            return jsonify({"status": "error", "message": f"Error serving image: {str(e)}"}), 500
    except Exception as e:
        current_app.logger.error(f"Exception in get_frame_image: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/api/analyzer/status', methods=['GET'])
@login_required
def get_analyzer_status():
    try:
        current_app.logger.debug("API Request: /api/analyzer/status")
        requested_camera_index = request.args.get('camera_index', default=0, type=int)
        all_cameras = request.args.get('all', default=False, type=bool)
        if all_cameras:
            status_data = {"cameras": {}}
            with analyzer_lock:
                for cam_idx in list(analyzer_threads.keys()):
                    thread_exists = cam_idx in analyzer_threads and analyzer_threads[cam_idx].is_alive()
                    running = cam_idx in analyzer_running and analyzer_running[cam_idx]
                    frame_count = analyzer_instances[cam_idx].frame_count if cam_idx in analyzer_instances and analyzer_instances[cam_idx] else 0
                    status_data["cameras"][str(cam_idx)] = {
                        "status": "active" if (thread_exists and running) else "inactive",
                        "frame_count": frame_count,
                        "camera_index": cam_idx
                    }
            return jsonify(status_data)
        else:
            with analyzer_lock:
                thread_exists = requested_camera_index in analyzer_threads and analyzer_threads.get(requested_camera_index) and analyzer_threads[requested_camera_index].is_alive()
                running = requested_camera_index in analyzer_running and analyzer_running.get(requested_camera_index)
                current_instance = analyzer_instances.get(requested_camera_index)
                frame_count = current_instance.frame_count if current_instance else 0
            status_data = {
                "status": "active" if (thread_exists and running) else "inactive",
                "frame_count": frame_count,
                "camera_index": requested_camera_index
            }
            current_app.logger.debug(f"Analyzer Status for camera {requested_camera_index}: {status_data}")
            return jsonify(status_data)
    except Exception as e:
        current_app.logger.error(f"Exception in get_analyzer_status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/api/analyzer/frames', methods=['GET'])
@login_required
def get_analyzer_frames():
    try:
        camera_index = request.args.get('camera_index', default=0, type=int)
        all_cameras = camera_index == -1
        frames = []
        camera_indices = []
        if all_cameras:
            camera_videos = Video.query.filter(Video.filename.like("camera_%_live")).all()
            camera_indices = [int(video.filename.split('_')[1]) for video in camera_videos]
        else:
            camera_indices = [camera_index]
        for cam_idx in camera_indices:
            try:
                camera_video = Video.query.filter_by(filename=f"camera_{cam_idx}_live").first()
                if camera_video:
                    limit_per_camera = int(request.args.get('limit', 30))
                    if all_cameras:
                        limit_per_camera = min(limit_per_camera // len(camera_indices), 10)
                    db_frames = Frame.query.filter_by(video_id=camera_video.id).order_by(Frame.id.desc()).limit(limit_per_camera).all()
                    if db_frames:
                        for frame in db_frames:
                            objects = DetectedObject.query.filter_by(frame_id=frame.id).all()
                            object_names = list(set(obj.object_name for obj in objects))
                            image_path = frame.image_path.replace('\\', '/') if frame.image_path else None
                            frames.append({
                                "id": frame.id,
                                "frame_number": frame.frame_number,
                                "path": f"/{image_path}" if image_path else None,
                                "timestamp": frame.timestamp.strftime('%Y-%m-%d %H:%M:%S') if frame.timestamp else None,
                                "objects": object_names,
                                "object_count": len(object_names),
                                "camera_index": cam_idx
                            })
            except Exception as e:
                current_app.logger.error(f"Error retrieving frames from database for camera {cam_idx}: {str(e)}")
        if frames:
            frames.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return jsonify({
                "status": "success",
                "frames": frames,
                "count": len(frames),
                "source": "database",
                "all_cameras": all_cameras
            })
        # Fallback to filesystem if DB is empty
        if not all_cameras:
            folder_path = os.path.join(current_app.config['REALTIME_FOLDER'], f"camera_{camera_index}")
            if not os.path.exists(folder_path):
                folder_path = current_app.config['REALTIME_FOLDER']
            if not os.path.exists(folder_path):
                return jsonify({
                    "status": "error",
                    "message": f"No real-time frames available for camera {camera_index}",
                    "camera_index": camera_index
                }), 404
            limit = int(request.args.get('limit', 30))
            try:
                for filename in sorted(os.listdir(folder_path), reverse=True)[:limit]:
                    if filename.endswith('.jpg'):
                        image_path = os.path.join(folder_path, filename).replace('\\', '/')
                        timestamp_parts = filename.split('_')[1:3]
                        timestamp = ' '.join(timestamp_parts) if len(timestamp_parts) >= 2 else None
                        frames.append({
                            "filename": filename,
                            "path": f"/{image_path}",
                            "timestamp": timestamp,
                            "full_path": os.path.abspath(os.path.join(folder_path, filename)),
                            "camera_index": camera_index
                        })
            except Exception as e:
                current_app.logger.error(f"Error listing analyzer frames: {str(e)}")
                return jsonify({
                    "status": "error", 
                    "message": str(e),
                    "camera_index": camera_index
                }), 500
        else:
            available_folders = []
            for d in os.listdir(current_app.config['REALTIME_FOLDER']):
                if d.startswith("camera_") and os.path.isdir(os.path.join(current_app.config['REALTIME_FOLDER'], d)):
                    try:
                        cam_idx = int(d.split('_')[1])
                        available_folders.append((cam_idx, os.path.join(current_app.config['REALTIME_FOLDER'], d)))
                    except (ValueError, IndexError):
                        continue
            if not available_folders:
                return jsonify({
                    "status": "error",
                    "message": "No camera folders found",
                    "all_cameras": True
                }), 404
            limit_per_camera = max(5, int(request.args.get('limit', 30)) // len(available_folders))
            for cam_idx, folder in available_folders:
                try:
                    for filename in sorted(os.listdir(folder), reverse=True)[:limit_per_camera]:
                        if filename.endswith('.jpg'):
                            image_path = os.path.join(folder, filename).replace('\\', '/')
                            timestamp_parts = filename.split('_')[1:3]
                            timestamp = ' '.join(timestamp_parts) if len(timestamp_parts) >= 2 else None
                            frames.append({
                                "filename": filename,
                                "path": f"/{image_path}",
                                "timestamp": timestamp,
                                "full_path": os.path.abspath(os.path.join(folder, filename)),
                                "camera_index": cam_idx
                            })
                except Exception as e:
                    current_app.logger.error(f"Error listing analyzer frames for camera {cam_idx}: {str(e)}")
        frames.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return jsonify({
            "status": "success",
            "frames": frames,
            "count": len(frames),
            "source": "filesystem",
            "all_cameras": all_cameras
        })
    except Exception as e:
        current_app.logger.error(f"Exception in get_analyzer_frames: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route('/api/stream')
@login_required
def video_stream():
    try:
        from analyzer_state import analyzers_globally_stopped
        if analyzers_globally_stopped:
            current_app.logger.warning("Global stop is active. Not starting analyzer for stream request.")
            return jsonify({"status": "error", "message": "Analyzers are globally stopped."}), 503

        current_app.logger.info("API Request: /api/stream")
        requested_camera_index = request.args.get('camera_index', type=int, default=0)
        camera_last_access[requested_camera_index] = time.time()
        check_inactive_cameras()
        with analyzer_lock:
            camera_running = (requested_camera_index in analyzer_running and 
                             analyzer_running[requested_camera_index] and
                             requested_camera_index in analyzer_threads and
                             analyzer_threads[requested_camera_index].is_alive() and
                             requested_camera_index in analyzer_instances and
                             analyzer_instances[requested_camera_index] is not None)
        if not camera_running:
            current_app.logger.warning(f"Stream requested for camera {requested_camera_index}, not running. Starting...")
            if not start_analyzer_thread(camera_index=requested_camera_index, show_video=False):
                current_app.logger.error(f"Failed to start analyzer thread for camera {requested_camera_index}.")
                return jsonify({"status": "error", "message": f"Analyzer not running for camera {requested_camera_index} and failed to start"}), 503
            time.sleep(15)
            with analyzer_lock:
                camera_running = (requested_camera_index in analyzer_running and 
                                 analyzer_running.get(requested_camera_index) and
                                 requested_camera_index in analyzer_instances and
                                 analyzer_instances.get(requested_camera_index) is not None)
            if not camera_running:
                current_app.logger.error(f"Analyzer failed to start for camera {requested_camera_index}.")
                return jsonify({"status": "error", "message": f"Failed to start analyzer for camera {requested_camera_index}"}), 503
        current_app.logger.info(f"Streaming from camera {requested_camera_index}...")

        @stream_with_context
        def generate_frames():
            while True:
                with analyzer_lock:
                    instance = analyzer_instances.get(requested_camera_index)
                if instance is not None:
                    frame = instance.get_current_frame()
                    if frame is not None:
                        ret, buffer = cv2.imencode('.jpg', frame)
                        if not ret:
                            continue
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    else:
                        time.sleep(0.05)
                else:
                    # Use print or logging here, not current_app.logger
                    print(f"Analyzer instance for camera {requested_camera_index} is None. Ending stream.")
                    break

        return Response(generate_frames(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as e:
        current_app.logger.error(f"Exception in video_stream: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/api/analyzer/start-all', methods=['POST'])
def start_all_analyzers_route():
    try:
        allow_analyzers_start()  # Allow analyzers to start again
        result = start_all_camera_analyzers()
        if not result or not isinstance(result, tuple) or len(result) != 2:
            current_app.logger.error("start_all_camera_analyzers did not return a tuple!")
            return jsonify({"status": "error", "message": "Internal error: camera analyzer start failed."}), 500
        started, cameras = result
        return jsonify({
            "status": "success",
            "started_count": started,
            "cameras": cameras
        })
    except Exception as e:
        current_app.logger.error(f"Error starting cameras: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
@main_bp.route('/api/analyzer/stop-all', methods=['POST'])
def stop_all_analyzers_route():
    try:
        stopped = stop_all_analyzers()
        return jsonify({
            "status": "success",
            "stopped_count": stopped
        })
    except Exception as e:
        current_app.logger.error(f"Error stopping cameras: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/realtime', methods=['GET'])
@login_required
def realtime_view():
    return render_template('realtime.html')

@main_bp.route('/api/analyzer/restart', methods=['POST'])
@login_required
def restart_analyzer():
    try:
        data = request.get_json()
        camera_index = data.get('camera_index')
        current_app.logger.info(f"API Request: /api/analyzer/restart with camera_index={camera_index}")
        if camera_index is None:
            return jsonify({"status": "error", "message": "No camera_index provided"}), 400
        try:
            camera_index = int(camera_index)
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": f"Invalid camera index: {camera_index}"}), 400
        stop_analyzer_thread(camera_index)
        time.sleep(2)
        current_app.logger.info(f"Starting new analyzer thread for camera {camera_index}...")
        started = start_analyzer_thread(camera_index=camera_index, show_video=False)
        if not started:
            return jsonify({"status": "error", "message": "Failed to start analyzer thread"}), 500
        return jsonify({"status": "pending", "message": f"Analyzer for camera {camera_index} is starting. Please poll status."}), 202
    except Exception as e:
        current_app.logger.error(f"Exception in restart_analyzer: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/settings', methods=['GET'])
@login_required
def settings():
    return render_template('settings.html', config=current_app.config['ANALYSIS_CONFIG'])

@main_bp.route('/settings/update', methods=['POST'])
@login_required
def update_settings():
    try:
        data = request.get_json()
        if not data or 'type' not in data or 'settings' not in data:
            return jsonify({
                'success': False,
                'message': 'Invalid request format'
            })
        config_type = data['type']
        new_settings = data['settings']
        analysis_config = current_app.config['ANALYSIS_CONFIG']
        if config_type not in analysis_config:
            return jsonify({
                'success': False,
                'message': f'Unknown configuration type: {config_type}'
            })
        for key, value in new_settings.items():
            if key in analysis_config[config_type]:
                if key == 'confidence' and (value < 0.1 or value > 0.9):
                    return jsonify({
                        'success': False,
                        'message': 'Confidence must be between 0.1 and 0.9'
                    })
                elif key == 'save_interval' and (value < 1 or value > 30):
                    return jsonify({
                        'success': False,
                        'message': 'Save interval must be between 1 and 30'
                    })
                elif key == 'frame_rate' and (value < 0.01 or value > 1):
                    return jsonify({
                        'success': False,
                        'message': 'Frame rate must be between 0.01 and 1'
                    })
                elif key == 'frame_interval' and (value < 1 or value > 30):
                    return jsonify({
                        'success': False,
                        'message': 'Frame interval must be between 1 and 30'
                    })
                elif key == 'min_objects' and (value < 1 or value > 10):
                    return jsonify({
                        'success': False,
                        'message': 'Minimum objects must be between 1 and 10'
                    })
                elif key == 'include_classes' and not isinstance(value, list):
                    return jsonify({
                        'success': False,
                        'message': 'Include classes must be a list'
                    })
                analysis_config[config_type][key] = value
        return jsonify({
            'success': True,
            'message': f'{config_type.capitalize()} settings updated successfully'
        })
    except Exception as e:
        current_app.logger.error(f"Error updating settings: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error updating settings: {str(e)}'
        })

@main_bp.route('/api/camera-thumbnail/<int:camera_index>', methods=['GET'])
@login_required
def get_camera_thumbnail(camera_index):
    try:
        from analyzer_state import analyzers_globally_stopped
        if analyzers_globally_stopped:
            # Always return offline placeholder if globally stopped
            placeholder_path = "static/images/camera-offline.jpg"
            if os.path.exists(placeholder_path):
                return send_from_directory("static/images", "camera-offline.jpg")
            else:
                # Generate a black image with "Camera X Offline"
                black_img = np.zeros((480, 640, 3), dtype=np.uint8)
                text = f"Camera {camera_index} Offline"
                cv2.putText(black_img, text, (80, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode('.jpg', black_img)
                if ret:
                    return Response(buffer.tobytes(), mimetype='image/jpeg')
                return jsonify({"status": "error", "message": "Camera offline"}), 503

        current_app.logger.debug(f"Thumbnail requested for camera {camera_index}")
        camera_last_access[camera_index] = time.time()
        check_inactive_cameras()
        with analyzer_lock:
            instance = analyzer_instances.get(camera_index)
            is_active = instance is not None and camera_index in analyzer_running and analyzer_running[camera_index]
        if not is_active:
            try:
                camera_video = Video.query.filter_by(filename=f"camera_{camera_index}_live").first()
                if camera_video:
                    recent_frame = Frame.query.filter_by(video_id=camera_video.id).order_by(Frame.id.desc()).first()
                    if recent_frame and recent_frame.image_path and os.path.exists(recent_frame.image_path):
                        return send_from_directory(
                            os.path.dirname(recent_frame.image_path), 
                            os.path.basename(recent_frame.image_path)
                        )
            except Exception as e:
                current_app.logger.error(f"Error getting thumbnail from database: {str(e)}")
        elif instance:
            try:
                frame = instance.get_current_frame()
                if frame is not None:
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        return Response(buffer.tobytes(), mimetype='image/jpeg')
            except Exception as e:
                current_app.logger.error(f"Error getting thumbnail from analyzer: {str(e)}")
        try:
            placeholder_path = "static/images/camera-offline.jpg"
            if os.path.exists(placeholder_path):
                return send_from_directory("static/images", "camera-offline.jpg")
            else:
                black_img = np.zeros((480, 640, 3), dtype=np.uint8)
                text = f"Camera {camera_index} Offline"
                cv2.putText(black_img, text, (80, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode('.jpg', black_img)
                if ret:
                    return Response(buffer.tobytes(), mimetype='image/jpeg')
        except Exception as e:
            current_app.logger.error(f"Error creating placeholder image: {str(e)}")
        return jsonify({"status": "error", "message": "Camera thumbnail not available"}), 404
    except Exception as e:
        current_app.logger.error(f"Exception in get_camera_thumbnail: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
