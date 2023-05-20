import tempfile
import threading
import time
import zipfile

from flask import send_file, after_this_request
from zipfile import ZipFile

from flask import Flask, render_template, request, send_from_directory, url_for, session
from flask_pymongo import PyMongo
import os
from flask import redirect
from werkzeug.utils import secure_filename
import uuid
import shutil
from PIL import Image
from functools import wraps
from bson.objectid import ObjectId

app = Flask(__name__)
app.config.from_pyfile('config.py')
mongo = PyMongo(app)

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


def cleanup_old_files(zip_filename):
    while True:
        time.sleep(5)
        if os.path.isfile(zip_filename):
            print(f"File to delete: {zip_filename}")

            creation_time = os.path.getctime(zip_filename)
            now = time.time()
            if creation_time < (now - 10):  # 1 hour
                os.remove(zip_filename)
                print(f"Delete {zip_filename}")
                break
        else:
            break


@app.route('/upload', methods=['POST'])
@login_required
def upload():
    category_name = request.form['category']
    category = mongo.db.categories.find_one({"name": category_name})
    if not category:
        return "Category not found", 404

    category_id = category['_id']
    photos = request.files.getlist('photos')
    original_folder = os.path.join(app.config['UPLOAD_FOLDER'], category_name, 'original')
    compressed_folder = os.path.join(app.config['UPLOAD_FOLDER'], category_name, 'compressed')

    for photo in photos:
        if photo and allowed_file(photo.filename):
            filename = secure_filename(generate_unique_filename(photo.filename))
            original_path = os.path.join(original_folder, filename)
            compressed_path = os.path.join(compressed_folder, filename)

            # Save original image
            photo.save(original_path)

            # Compress and save the image
            compress_and_save_image(original_path, compressed_path)

            # Save image information in MongoDB
            mongo.db.images.insert_one({
                'filename': filename,
                'category_id': category_id,
                'description': photo.filename.split('.')[0]  # Empty description initially
            })

    return redirect(url_for('category', category=category_name))


@app.route('/')
def index():
    # Fetch the categories from MongoDB, sorted by the 'order' field
    categories = list(mongo.db.categories.find().sort('order'))
    return render_template('index.jinja2', categories=categories)


@app.route('/category/<category>')
def category(category):
    """
    compressed_folder = os.path.join(app.config['UPLOAD_FOLDER'], category, 'compressed')
    image_files = os.listdir(compressed_folder)
    category_info = mongo.db.categories.find_one({"name": category})
    cover_image = category_info.get("cover_image")
    return render_template('category.jinja2', category=category, images=image_files, cover_image=cover_image)
"""
    # Get the category information
    category_info = mongo.db.categories.find_one({"name": category})
    cover_image = category_info.get("cover_image")

    # Fetch the image files from MongoDB
    image_files = list(mongo.db.images.find({"category_id": category_info["_id"]}))

    return render_template('category.jinja2', category=category, images=image_files, cover_image=cover_image)


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

        # Add the new category to the MongoDB collection
        mongo.db.categories.insert_one({
            'name': category_name,
            'order': mongo.db.categories.count_documents({}),  # Set the order to the current number of categories
            'cover_image': None
        })

    return redirect(url_for('index'))


@app.route('/move_category/<category_name>/<direction>')
@login_required
def move_category(category_name, direction):
    if direction not in ['up', 'down']:
        return 'Invalid direction', 400

    category = mongo.db.categories.find_one({'name': category_name})

    if not category:
        return 'Category not found', 404

    if direction == 'up':
        # Find the previous category
        prev_category = mongo.db.categories.find_one({'order': category['order'] - 1})
        if prev_category:
            # Swap the order of the current category and the previous category
            mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'order': category['order'] - 1}})
            mongo.db.categories.update_one({'_id': prev_category['_id']}, {'$set': {'order': prev_category['order'] + 1}})
    else:
        # Find the next category
        next_category = mongo.db.categories.find_one({'order': category['order'] + 1})
        if next_category:
            # Swap the order of the current category and the next category
            mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'order': category['order'] + 1}})
            mongo.db.categories.update_one({'_id': next_category['_id']}, {'$set': {'order': next_category['order'] - 1}})

    return redirect(url_for('index'))


@app.route('/delete_category/<category>', methods=['POST'])
@login_required
def delete_category(category):
    # Get the order and id of the category being deleted
    category_info = mongo.db.categories.find_one({'name': category})
    category_order = category_info['order']
    category_id = category_info['_id']

    # Delete the images associated with the category
    mongo.db.images.delete_many({'category_id': category_id})

    # Delete the category from the database
    mongo.db.categories.delete_one({'_id': category_id})

    # Decrease the order of all categories that come after the one being deleted
    mongo.db.categories.update_many(
        {'order': {'$gt': category_order}},
        {'$inc': {'order': -1}}
    )

    # Delete the category directory from the filesystem
    category_path = os.path.join(app.config['UPLOAD_FOLDER'], category)
    shutil.rmtree(category_path)

    return redirect(url_for('index'))


@app.route('/set_cover_image/<category_name>/<image_name>')
@login_required
def set_cover_image(category_name, image_name):
    category = mongo.db.categories.find_one({'name': category_name})
    if not category:
        return 'Category not found', 404

    # Update the cover image in the MongoDB database
    mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'cover_image': image_name}})

    return redirect(url_for('category', category=category_name))


@app.route('/update_description/<image_id>', methods=['POST'])
@login_required
def update_description(image_id):
    new_description = request.form.get('new_description')
    mongo.db.images.update_one({'_id': ObjectId(image_id)}, {'$set': {'description': new_description}})
    return redirect(request.referrer)


@app.route('/delete_image/<image>', methods=['POST'])
@login_required
def delete_image(image):
    pass


@app.route('/download/<category>', methods=['GET'])
def download_category(category):
    # Create a temporary zip file
    zip_filename = os.path.join(app.config['TEMP_FOLDER'], f"{category}_{uuid.uuid4()}.zip")
    with zipfile.ZipFile(zip_filename, 'w') as zipf:
        # Iterate over all images in the category
        category_id = mongo.db.categories.find_one({"name": category})["_id"]
        image_files = mongo.db.images.find({'category_id': category_id})
        for image in image_files:
            # Use the 'original' images
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], category, 'original', image['filename'])
            # Add the file to the zip archive, with a path within the archive
            zipf.write(image_path, arcname=os.path.join(category, image['filename']))

        print(zip_filename)

    cleanup_thread = threading.Thread(target=cleanup_old_files, args=(zip_filename,))
    cleanup_thread.start()

    return send_file(zip_filename, mimetype='application/zip', as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)
