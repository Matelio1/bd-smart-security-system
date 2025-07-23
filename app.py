import os
import logging
import threading
import time
from flask import Flask
from flask_login import LoginManager
from db_models import db, User, configure_db, init_db, Video, Frame, DetectedObject
from analyzer import RealtimeAnalyzer
from datetime import datetime
import datetime as dt

from config import Config

# --- Flask app setup ---
app = Flask(__name__)
app.config.from_object(Config)

app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not app.logger.handlers:
    app.logger.addHandler(handler)

configure_db(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'main.login'

# --- Import analyzer state and logic from analyzer_state.py ---
from analyzer_state import (
    check_inactive_cameras, start_all_camera_analyzers, set_app_context
)

# --- Set app context for analyzer_state.py ---
set_app_context(
    app,
    {
        'db': db,
        'Video': Video,
        'Frame': Frame,
        'DetectedObject': DetectedObject
    },
    RealtimeAnalyzer
)

def start_background_tasks():
    def run_maintenance():
        while True:
            try:
                time.sleep(60)
                with app.app_context():
                    check_inactive_cameras()
            except Exception as e:
                app.logger.error(f"Error in maintenance task: {e}")

    # Start the old activity frame deletion task
    def delete_old_files():
        while True:
            try:
                time.sleep(86400)  # Run every 24 hours
                with app.app_context():
                    now = datetime.now()
                    retention_days = app.config["FILE_RETENTION_DAYS"]
                    app.logger.info(f"Running delete_old_files task. Retention: {retention_days} days.")
                    
                    # Calculate the cutoff date
                    cutoff_date = now - dt.timedelta(days=retention_days)
                    
                    # Track folders that might need cleanup after file deletion
                    folders_to_check = set()
                    
                    # APPROACH 1: Start with database Frame records and delete from there
                    # Find frames older than retention period
                    old_frames = Frame.query.filter(Frame.timestamp < cutoff_date).all()
                    frame_count = len(old_frames)
                    
                    if frame_count > 0:
                        app.logger.info(f"Found {frame_count} old frames in database to delete")
                        
                        for frame in old_frames:
                            try:
                                # Get the image path
                                image_path = frame.image_path
                                
                                # Delete the physical file if it exists and is valid
                                if image_path and os.path.exists(image_path) and os.path.isfile(image_path):
                                    try:
                                        # Add parent directory to cleanup list
                                        parent_dir = os.path.dirname(image_path)
                                        folders_to_check.add(parent_dir)
                                        
                                        os.remove(image_path)
                                        app.logger.info(f"Deleted file from disk: {image_path}")
                                    except OSError as e_file:
                                        app.logger.error(f"Failed to delete file {image_path}: {e_file}")
                                
                                # Delete the database record (will cascade to DetectedObject)
                                db.session.delete(frame)
                                app.logger.info(f"Deleted frame record ID {frame.id} from database")
                            except Exception as e_frame:
                                app.logger.error(f"Error processing frame ID {frame.id}: {e_frame}")
                                # Continue with other frames even if one fails
                        
                        # Commit all database changes
                        try:
                            db.session.commit()
                            app.logger.info(f"Successfully deleted {frame_count} old frames from database")
                        except Exception as e_commit:
                            app.logger.error(f"Error committing database changes: {e_commit}")
                            db.session.rollback()
                    else:
                        app.logger.info("No old frames found in database")
                    
                    # APPROACH 2: Find orphaned files not in the database
                    # Handle videos folder
                    videos_folder = app.config['VIDEOS_FOLDER']
                    output_folder = app.config['OUTPUT_FOLDER']
                    
                    # Function to check for old files by modification time
                    def delete_old_files_by_mtime(folder_path, log_prefix=""):
                        if not os.path.exists(folder_path):
                            app.logger.warning(f"{log_prefix} Folder {folder_path} does not exist")
                            return
                            
                        for root, dirs, files in os.walk(folder_path):
                            for filename in files:
                                file_path = os.path.join(root, filename)
                                try:
                                    # Check if this file exists in the database
                                    frame_exists = Frame.query.filter_by(image_path=file_path).first()
                                    if frame_exists:
                                        # Skip files that are tracked in the database
                                        continue
                                        
                                    # Check file age
                                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                                    if (now - file_time).days > retention_days:
                                        # Add parent directory to cleanup list
                                        folders_to_check.add(os.path.dirname(file_path))
                                        
                                        os.remove(file_path)
                                        app.logger.info(f"{log_prefix} Deleted orphaned file: {file_path}")
                                except Exception as e:
                                    app.logger.error(f"{log_prefix} Error checking file {file_path}: {e}")
                    
                    # Delete orphaned files in videos folder
                    delete_old_files_by_mtime(videos_folder, "VIDEOS:")
                    
                    # Delete orphaned files in output folder
                    delete_old_files_by_mtime(output_folder, "OUTPUT:")
                    
                    # Clean up empty folders (starting from deepest paths first)
                    if folders_to_check:
                        app.logger.info(f"Checking {len(folders_to_check)} folders for cleanup")
                        
                        # Sort folders by depth (deepest first) to ensure child folders are processed before parents
                        sorted_folders = sorted(folders_to_check, key=lambda x: x.count(os.sep), reverse=True)
                        
                        # Function to recursively check and remove empty directories
                        def remove_if_empty(folder_path, base_folder):
                            # Don't delete the base output or videos folders
                            if folder_path == base_folder:
                                return
                                
                            try:
                                if os.path.exists(folder_path) and os.path.isdir(folder_path):
                                    # Check if directory is empty (no files and no subdirectories)
                                    if not os.listdir(folder_path):
                                        parent_dir = os.path.dirname(folder_path)
                                        os.rmdir(folder_path)
                                        app.logger.info(f"Removed empty folder: {folder_path}")
                                        
                                        # Recursively check parent (if it's not the output root folder)
                                        if parent_dir not in [videos_folder, output_folder]:
                                            remove_if_empty(parent_dir, base_folder)
                            except Exception as e:
                                app.logger.error(f"Error removing empty folder {folder_path}: {e}")
                        
                        # Process each folder
                        for folder in sorted_folders:
                            # Determine which base folder this belongs to
                            if folder.startswith(videos_folder):
                                base = videos_folder
                            elif folder.startswith(output_folder):
                                base = output_folder
                            else:
                                # Unknown folder, skip it
                                continue
                                
                            remove_if_empty(folder, base)
                    
            except Exception as e:
                app.logger.error(f"Error in delete_old_files task: {e}")
                with app.app_context():
                    db.session.rollback()

    # Start the maintenance thread
    maintenance_thread = threading.Thread(target=run_maintenance, daemon=True)
    maintenance_thread.start()
    
    # Start the file deletion thread
    delete_files_thread = threading.Thread(target=delete_old_files, daemon=True)
    delete_files_thread.start()

    app.logger.info("Started background maintenance and file deletion tasks")

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

from views import main_bp
app.register_blueprint(main_bp)

if __name__ == '__main__':
    init_db(app)
    app.logger.info("Database Initialized.")
    start_background_tasks()
    app.logger.info("Starting analyzers for available cameras...")
    started, cameras = start_all_camera_analyzers()
    app.logger.info(f"Started {started} camera analyzers for cameras: {cameras}")
    app.logger.info("Starting Flask development server...")
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)