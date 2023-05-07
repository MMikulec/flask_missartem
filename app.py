from flask import Flask, render_template, request, send_from_directory, url_for
import os
from flask import redirect
from werkzeug.utils import secure_filename
import uuid
from PIL import Image
from flask import session
from functools import wraps

app = Flask(__name__)
app.config.from_pyfile('config.py')

# #################### LOGIN ####################
# Example user for testing purposes
users = {
    'example_user': {
        'username': 'example_user',
        'password': 'example_password'
    }
}


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username in users and users[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return 'Invalid username or password', 401
    return render_template('login.jinja2')


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))
# #################### LOGIN END ####################


# Add this function to generate unique filenames
def generate_unique_filename(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return f"{uuid.uuid4().hex}{ext}"


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def compress_and_save_image(input_path, output_path, max_size=(800, 800), quality=85):
    with Image.open(input_path) as img:
        img.thumbnail(max_size, Image.ANTIALIAS)
        img.save(output_path, format=img.format, quality=quality)


@app.route('/upload', methods=['POST'])
@login_required
def upload():
    category = request.form['category']
    photos = request.files.getlist('photos')
    original_folder = os.path.join(app.config['UPLOAD_FOLDER'], category, 'original')
    compressed_folder = os.path.join(app.config['UPLOAD_FOLDER'], category, 'compressed')

    for photo in photos:
        if photo and allowed_file(photo.filename):
            filename = secure_filename(generate_unique_filename(photo.filename))
            original_path = os.path.join(original_folder, filename)
            compressed_path = os.path.join(compressed_folder, filename)

            # Save original image
            photo.save(original_path)

            # Compress and save the image
            compress_and_save_image(original_path, compressed_path)

    return redirect(url_for('category', category=category))


@app.route('/')
def index():
    all_folders = os.listdir(app.config['UPLOAD_FOLDER'])
    categories = []
    for folder in all_folders:
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
        if os.path.isdir(folder_path):
            original_path = os.path.join(folder_path, 'original')
            compressed_path = os.path.join(folder_path, 'compressed')
            if os.path.exists(original_path) and os.path.exists(compressed_path):
                # Get the first image in the compressed folder as the cover image
                cover_image = None
                compressed_images = os.listdir(compressed_path)
                if compressed_images:
                    cover_image = compressed_images[0]
                categories.append({'name': folder, 'cover_image': cover_image})
    return render_template('index.jinja2', categories=categories)


@app.route('/category/<category>')
def category(category):
    compressed_folder = os.path.join(app.config['UPLOAD_FOLDER'], category, 'compressed')
    image_files = os.listdir(compressed_folder)
    return render_template('category.jinja2', category=category, images=image_files)


@app.route('/uploads/<path:subpath>')
def serve_uploads(subpath):
    return send_from_directory(app.config['UPLOAD_FOLDER'], subpath)


@app.route('/uploads/original/<path:subpath>')
def serve_original_uploads(subpath):
    return send_from_directory(app.config['UPLOAD_FOLDER'], subpath)


@app.route('/create_category', methods=['POST'])
@login_required
def create_category():
    category_name = request.form.get('category_name')
    if category_name:
        new_category_path = os.path.join(app.config['UPLOAD_FOLDER'], category_name)
        os.makedirs(new_category_path)
        os.makedirs(os.path.join(new_category_path, 'original'))
        os.makedirs(os.path.join(new_category_path, 'compressed'))
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
