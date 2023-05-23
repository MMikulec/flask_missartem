import threading
import time
import zipfile

from flask import send_file

from flask import Flask, render_template, request, send_from_directory, url_for, session, make_response, flash, abort
from flask_pymongo import PyMongo
import os
from datetime import datetime
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

# Example user for testing purposes
users = {
    'example_user': {
        'username': 'example_user',
        'password': 'example_password'
    }
}


# ERROR HANDLE
@app.errorhandler(404)
def page_not_found(e):
    return render_template("error/404.jinja2", e=e.description), 404


# #################### LOGIN ####################
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/login', methods=['GET', 'POST'], endpoint='private.login')
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


@app.route('/logout', endpoint='private.logout')
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
        img.thumbnail(max_size, Image.LANCZOS)
        img.save(output_path, format=img.format, quality=quality)


def cleanup_old_files(zip_filename):
    while True:
        time.sleep(app.config['REMOVE_ZIP'])
        if os.path.isfile(zip_filename):
            print(f"File to delete: {zip_filename}")

            creation_time = os.path.getctime(zip_filename)
            now = time.time()
            if creation_time < (now - app.config['REMOVE_ZIP']):  # settings in config.py
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
        # return "Category not found", 404
        abort(404, description=f"Category '{category}' doesn't exist.")

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
                'description': photo.filename.split('.')[0],  # Empty description initially
                'uploaded_at': datetime.now()
            })

            # When updating an album
            mongo.db.categories.update_one(
                {'_id': ObjectId(category_id)},
                {
                    '$set': {
                        'updated_at': datetime.now()
                    }
                }
            )

    return redirect(url_for('category', category=category_name))


@app.route('/')
def index():
    # Fetch the categories from MongoDB, sorted by the 'order' field
    categories = list(mongo.db.categories.find().sort('order').sort('order', -1))
    return render_template('index.jinja2', categories=categories)


@app.route('/category/<category>')
def category(category):
    # Get the category information
    category_info = mongo.db.categories.find_one({"name": category})

    if not category_info:
        abort(404, description=f"Category '{category}' doesn't exist.")

    cover_image = category_info.get("cover_image")

    # Fetch the image files from MongoDB
    image_files = list(mongo.db.images.find({"category_id": category_info["_id"]}))

    return render_template('category.jinja2', category=category, images=image_files,
                           cover_image=cover_image, category_info=category_info)


@app.route('/uploads/<path:sub_path>')
def serve_uploads(sub_path):
    return send_from_directory(app.config['UPLOAD_FOLDER'], sub_path)


@app.route('/uploads/original/<path:sub_path>')
def serve_original_uploads(sub_path):
    return send_from_directory(app.config['UPLOAD_FOLDER'], sub_path)


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
            'cover_image': None,
            'description': '',
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'keywords': ''
        })

    return redirect(url_for('index'))


@app.route('/move_category/<category_name>/<direction>')
@login_required
def move_category(category_name, direction):
    if direction not in ['up', 'down']:
        return 'Invalid direction', 400

    category = mongo.db.categories.find_one({'name': category_name})

    if not category:
        # return 'Category not found', 404
        abort(404, description=f"Category '{category}' doesn't exist.")

    if direction == 'down':  # Look for the category with a lower order
        prev_category = mongo.db.categories.find_one({'order': category['order'] - 1})
        if prev_category:
            mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'order': category['order'] - 1}})
            mongo.db.categories.update_one({'_id': prev_category['_id']}, {'$set': {'order': prev_category['order'] + 1}})
    else:  # 'up', so look for the category with a higher order
        next_category = mongo.db.categories.find_one({'order': category['order'] + 1})
        if next_category:
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


@app.route('/update_category/<category_name>', methods=['POST'])
@login_required
def update_category_name(category_name):
    category = mongo.db.categories.find_one({'name': category_name})
    new_name = request.form.get('new_cat_name')

    old_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], category['name'])
    new_folder_path = os.path.join(app.config['UPLOAD_FOLDER'], new_name)

    try:
        os.rename(old_folder_path, new_folder_path)
    except Exception as e:
        flash("Could not rename the folder: ", str(e))
        return redirect(request.referrer)

    # Update the category name in the MongoDB database
    mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'name': new_name}})

    return redirect(request.referrer)


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


@app.route('/set_cover_image/<category_name>/<image_name>')
@login_required
def set_cover_image(category_name, image_name):
    category = mongo.db.categories.find_one({'name': category_name})
    if not category:
        # return 'Category not found', 404
        abort(404, description=f"Category '{category}' doesn't exist.")

    # Update the cover image in the MongoDB database
    mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'cover_image': image_name}})

    return redirect(url_for('category', category=category_name))


@app.route('/update_description/<item_type>/<item_id>', methods=['POST'])
@login_required
def update_description(item_type, item_id):
    if item_type == 'image':
        collection = mongo.db.images
    elif item_type == 'category':
        collection = mongo.db.categories
    else:
        return "Invalid item type", 400  # HTTP 400 Bad Request

    new_description = request.form.get('new_description')
    collection.update_one({'_id': ObjectId(item_id)}, {'$set': {'description': new_description}})
    return redirect(request.referrer)


@app.route('/update_keywords/<category_id>', methods=['POST'])
@login_required
def update_keywords(category_id):
    new_keywords = request.form.get('new_keywords')
    mongo.db.categories.update_one({'_id': ObjectId(category_id)}, {'$set': {'keywords': new_keywords}})

    return redirect(request.referrer)


@app.route('/delete_image/<image_id>', methods=['POST'])
@login_required
def delete_image(image_id):
    # Fetch the image from the database
    image = mongo.db.images.find_one({'_id': ObjectId(image_id)})

    # Get the category_id from the image
    category_id = image.get('category_id')

    # Look up the category name in the categories collection
    category = mongo.db.categories.find_one({'_id': ObjectId(category_id)})
    category_name = category.get('name')

    # Get the image filename
    filename = image.get('filename')

    # Delete the image document from MongoDB
    mongo.db.images.delete_one({'_id': ObjectId(image_id)})

    # When updating an album
    mongo.db.categories.update_one(
        {'_id': ObjectId(category_id)},
        {
            '$set': {
                'updated_at': datetime.now()
            }
        }
    )

    # Delete the image file from the server
    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], category_name, 'original', filename))
    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], category_name, 'compressed', filename))

    return redirect(request.referrer)


@app.route('/sitemap.xml', methods=['GET'])
def sitemap():
    """Generate sitemap.xml including album and image data."""
    pages = []

    # static pages
    for rule in app.url_map.iter_rules():
        if "GET" in rule.methods and len(rule.arguments) == 0:
            # Exclude 'private' routes
            if 'private' not in rule.endpoint:
                pages.append(
                    [url_for(rule.endpoint, _external=True), datetime.now().date().isoformat(), []]
                )

    # album and image data
    albums = mongo.db.categories.find()
    for album in albums:
        url = url_for('category', category=album['name'], _external=True)
        lastmod = album['updated_at'].isoformat()
        image_data = []
        images = mongo.db.images.find({'category_id': album['_id']})
        for image in images:
            image_url = url_for('serve_uploads', sub_path=album['name'] + '/compressed/' + image['filename'],
                                _external=True)
            image_caption = image['description']
            image_data.append([image_url, image_caption])
        pages.append([url, lastmod, image_data])

    sitemap_xml = render_template('sitemap_template.xml', pages=pages)
    response = make_response(sitemap_xml)
    response.headers["Content-Type"] = "application/xml"

    return response


@app.route('/robots.txt')
def robots():
    response = make_response(render_template('robots.jinja2'))
    response.headers["Content-Type"] = "text/plain"
    return response


if __name__ == '__main__':
    app.run(debug=True)
