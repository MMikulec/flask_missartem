import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'images')
TEMP_FOLDER = os.path.join(BASE_DIR, 'temp')

SECRET_KEY = 'your-secret-key'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MONGO_URI = "mongodb://localhost:27017/portfolio"

REMOVE_ZIP = 10  # remove zip for download after seconds

ARTIST = {
    "name": "Michaela Mikulcová",
    "nickname": "MissArtem",
    "website": "www.missartem.sk"
}
