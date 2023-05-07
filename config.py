import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'images')

SECRET_KEY = 'your-secret-key'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MONGO_URI = "mongodb://localhost:27017/portfolio"
