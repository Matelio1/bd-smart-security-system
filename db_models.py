from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import os
from enum import IntEnum

# Initialize database without binding to an app
db = SQLAlchemy()

# Object type mapping for standardized object classification
class ObjectType(IntEnum):
    UNKNOWN = 0
    PERSON = 1
    CAR = 2
    TRUCK = 3
    BUS = 4
    MOTORCYCLE = 5
    BICYCLE = 6
    DOG = 7
    CAT = 8
    # Add more object types as needed

# Mapping from string names to object type codes
OBJECT_TYPE_MAPPING = {
    'person': ObjectType.PERSON,
    'car': ObjectType.CAR,
    'truck': ObjectType.TRUCK,
    'bus': ObjectType.BUS,
    'motorcycle': ObjectType.MOTORCYCLE,
    'bicycle': ObjectType.BICYCLE,
    'dog': ObjectType.DOG,
    'cat': ObjectType.CAT,
    # Add more mappings as needed
}

# Database Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
        
    def __repr__(self):
        return f'<User {self.username}>'

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=db.func.current_timestamp())
    analysis_result = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Relationship to frames
    frames = db.relationship('Frame', backref='video', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<Video {self.filename}>'

class Frame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    frame_number = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    image_path = db.Column(db.String(255), nullable=True)  # Optional storage of the frame image
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    object_count = db.Column(db.Integer, default=0)  # Track number of objects in frame
    
    # Relationship to detected objects
    detected_objects = db.relationship('DetectedObject', backref='frame', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<Frame {self.frame_number} of Video ID {self.video_id} with {self.object_count} objects>'
    
    def update_object_count(self):
        """Update the object count based on detected objects"""
        self.object_count = DetectedObject.query.filter_by(frame_id=self.id).count()
        return self.object_count
    
    def get_object_counts_by_type(self):
        """Returns a dictionary with counts of each object type in this frame"""
        result = {}
        objects = DetectedObject.query.filter_by(frame_id=self.id).all()
        
        for obj in objects:
            if obj.object_name not in result:
                result[obj.object_name] = 0
            result[obj.object_name] += 1
            
        return result

class DetectedObject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    object_name = db.Column(db.String(100), nullable=False)
    object_type = db.Column(db.Integer, default=0)  # Numeric code for object type
    probability = db.Column(db.Float, nullable=False)
    # Bounding box coordinates (optional)
    x_min = db.Column(db.Float, nullable=True)
    y_min = db.Column(db.Float, nullable=True)
    x_max = db.Column(db.Float, nullable=True)
    y_max = db.Column(db.Float, nullable=True)
    frame_id = db.Column(db.Integer, db.ForeignKey('frame.id'), nullable=False)
    
    def __repr__(self):
        return f'<DetectedObject {self.object_name} (Type: {self.object_type}, {self.probability:.2f}) in Frame ID {self.frame_id}>'
    
    @staticmethod
    def get_type_code(object_name):
        """Convert object name string to type code"""
        return OBJECT_TYPE_MAPPING.get(object_name.lower(), ObjectType.UNKNOWN)
    
    @staticmethod
    def get_type_name(type_code):
        """Convert type code to name"""
        for name, code in OBJECT_TYPE_MAPPING.items():
            if code == type_code:
                return name
        return "unknown"

def configure_db(app):
    # Configure SQLite database
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize app with extension
    db.init_app(app)

def init_db(app):
    with app.app_context():
        db.create_all()

def reset_db(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

def migrate_db(app):
    """Recreates database tables - WARNING: this will delete existing data"""
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Database schema reset and recreated")
