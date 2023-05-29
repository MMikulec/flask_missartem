import threading
import time
import zipfile
import os
import uuid
import shutil
import piexif
import importlib

from flask import send_file, Flask, render_template, request, send_from_directory, url_for, session, make_response, \
    flash, abort, redirect, Response
from flask_pymongo import PyMongo

from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from functools import wraps
from bson.objectid import ObjectId
from bson.json_util import dumps
from datetime import datetime, timedelta

app = Flask(__name__)
if os.getenv('ENVIRONMENT') == 'PRODUCTION':
    app.config.from_pyfile('production.py')
else:
    app.config.from_pyfile('config.py')
mongo = PyMongo(app)


"""def init_mongo():
    global mongo
    mongo = PyMongo(app)

    if not mongo.db.users.find_one({'username': 'admin'}):
        hashed_password = generate_password_hash('password')
        mongo.db.users.insert_one({'username': 'admin', 'password': hashed_password})
        print('Admin user added successfully.')
    else:
        print('Admin user already exists.')


if os.getenv('ENVIRONMENT') == 'PRODUCTION':
    print("PRODUCTION")
    postfork = importlib.import_module('uwsgidecorators').postfork
    postfork(init_mongo)
else:
    init_mongo()"""


NAME = app.config['ARTIST']['name']
NICKNAME = app.config['ARTIST']['nickname']
WEBSITE = app.config['ARTIST']['website']


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

        user = mongo.db.users.find_one({'username': username})

        if user:
            if 'lockout_until' in user and user['lockout_until'] > datetime.utcnow():
                flash('Too many failed login attempts. Please try again later.', 'danger')
                return render_template('login.jinja2'), 429
            else:
                # If lockout period is over, reset login_attempts to 0 and remove the lockout_until field
                if 'lockout_until' in user and user['lockout_until'] <= datetime.utcnow():
                    mongo.db.users.update_one(
                        {'username': username},
                        {'$set': {'login_attempts': 0}, '$unset': {'lockout_until': ""}}
                    )
                    user = mongo.db.users.find_one({'username': username})  # Retrieve updated user data

                if check_password_hash(user['password'], password):
                    session['username'] = username
                    # Reset login attempts and remove lockout_until after successful login
                    mongo.db.users.update_one(
                        {'username': username},
                        {'$set': {'login_attempts': 0}, '$unset': {'lockout_until': ""}}
                    )
                    flash('Logged in successfully.', 'success')
                    return redirect(url_for('index'))
                else:
                    # Increment login_attempts only if user is not in lockout period
                    mongo.db.users.update_one(
                        {'username': username},
                        {'$inc': {'login_attempts': 1}}
                    )
                    user = mongo.db.users.find_one({'username': username})  # Retrieve updated user data

                    # If this is the 5th failed attempt, set lockout period
                    if user.get('login_attempts', 0) >= 5:
                        mongo.db.users.update_one(
                            {'username': username},
                            {'$set': {'lockout_until': datetime.utcnow() + timedelta(minutes=15)}}
                        )
                        flash('Too many failed login attempts. Your account has been temporarily locked.', 'danger')
                    else:
                        flash('Invalid username or password', 'danger')
                        return render_template('login.jinja2'), 401

        else:
            flash('Invalid username or password', 'danger')
            return render_template('login.jinja2'), 401

    return render_template('login.jinja2')


@app.route('/logout', endpoint='private.logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))


@app.route('/change-password', methods=['GET', 'POST'], endpoint='private.change_password')
def change_password():
    # Check if user is logged in
    if 'username' not in session:
        flash('You must be logged in to change your password.', 'danger')
        return redirect(url_for('private.login'))

    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        username = session['username']
        user = mongo.db.users.find_one({'username': username})

        # Debugging print statements
        print("Stored hashed password:", user['password'])
        print("Entered old password:", old_password)
        print("Hash of entered old password:", generate_password_hash(old_password))

        if not user or not check_password_hash(user['password'], old_password):
            flash('Old password is incorrect.', 'danger')
            return redirect(url_for('private.change_password'))

        if new_password != confirm_password:
            flash('New password and confirm password do not match.', 'danger')
            return redirect(url_for('private.change_password'))

        hashed_password = generate_password_hash(new_password)
        mongo.db.users.update_one({'username': username}, {'$set': {'password': hashed_password}})

        flash('Password changed successfully.', 'success')
        return redirect(url_for('index'))

    return render_template('change_password.jinja2')


# #################### LOGIN END ####################


# Add this function to generate unique filenames
def generate_unique_filename(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return f"{uuid.uuid4().hex}{ext}"


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def compress_and_save_image(input_path, output_path, description, max_size=(800, 800), quality=85):
    with Image.open(input_path) as img:
        img.thumbnail(max_size, Image.LANCZOS)

        if img.format == "JPEG":
            # Load existing exif data if any
            if "exif" in img.info:
                # Load existing exif data
                exif_dict = piexif.load(img.info["exif"])
            else:
                # Initialize an empty exif data structure if no exif data is present
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None, "Interoperability": {}}

            # Set your custom metadata
            exif_dict["0th"][piexif.ImageIFD.Artist] = f"{NICKNAME} - {NAME}".encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = f"{WEBSITE} - {description}".encode('utf-8')
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = f"Image hosted at {WEBSITE}".encode('utf-8')

            # Set your custom metadata
            # exif_dict["0th"][piexif.ImageIFD.Make] = u"Marek".encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.Software] = f"{WEBSITE}".encode('utf-8')

            # Dump exif data
            exif_bytes = piexif.dump(exif_dict)

            # Save the image with the updated exif data
            img.save(output_path, format=img.format, quality=quality, exif=exif_bytes)

        elif img.format == "PNG":
            # Create dictionary with metadata
            metadata = PngInfo()

            # Adding some PNG text metadata
            metadata.add_text('Author', f"{NICKNAME} - {NAME}")
            metadata.add_text('Software', f"{WEBSITE}")
            metadata.add_text('Description', f"{WEBSITE} - {description}")
            metadata.add_text('Comment', f"Image hosted at {WEBSITE}")

            # Save the image with added metadata
            img.save(output_path, format=img.format, quality=quality, pnginfo=metadata)

        else:
            # If the image is neither JPEG nor PNG, it is saved without metadata
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
            description = photo.filename.split('.')[0]

            # Save original image
            photo.save(original_path)

            # Compress and save the image
            compress_and_save_image(original_path, compressed_path, description=description)

            # Save image information in MongoDB
            mongo.db.images.insert_one({
                'filename': filename,
                'category_id': category_id,
                'description': description,
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
    category_name = request.form.get('category_name').lower()
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
            mongo.db.categories.update_one({'_id': prev_category['_id']},
                                           {'$set': {'order': prev_category['order'] + 1}})
    else:  # 'up', so look for the category with a higher order
        next_category = mongo.db.categories.find_one({'order': category['order'] + 1})
        if next_category:
            mongo.db.categories.update_one({'_id': category['_id']}, {'$set': {'order': category['order'] + 1}})
            mongo.db.categories.update_one({'_id': next_category['_id']},
                                           {'$set': {'order': next_category['order'] - 1}})

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
        flash(f"Could not rename the folder: {str(e)}", "danger")
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

    # New thread for delete .zip file
    cleanup_thread = threading.Thread(target=cleanup_old_files, args=(zip_filename,))
    cleanup_thread.start()

    return send_file(zip_filename, mimetype='application/zip', as_attachment=True)


@app.route('/set_cover_image/<category_name>/<image_name>')
@login_required
def set_cover_image(category_name, image_name):
    category = mongo.db.categories.find_one({'name': category_name})
    if not category:
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


@app.route('/rss.xml', methods=['GET'])
def rss():
    """Generate rss.xml including album and image data."""
    # album and image data
    albums = mongo.db.categories.find().sort("updated_at", -1)
    album_list = []
    for album in albums:
        album['images'] = list(mongo.db.images.find({'category_id': album['_id']}))
        album_list.append(album)

    rss_xml = render_template('rss.xml', albums=album_list, artist=NAME)
    response = make_response(rss_xml)
    response.headers["Content-Type"] = "application/rss+xml; charset=utf-8"

    return response


@app.route('/robots.txt')
def robots():
    response = make_response(render_template('robots.jinja2'))
    response.headers["Content-Type"] = "text/plain"
    return response


@app.route('/api/categories', methods=['GET'])
def get_albums():
    albums = mongo.db.categories.find()
    data = []
    for album in albums:
        item = {
            'id': str(album['_id']),
            'name': album['name'],
            'order': album['order'],
            'cover_image': url_for('serve_uploads', sub_path=album['name'] + '/compressed/' + album['cover_image'],
                                   _external=True) if 'cover_image' in album and album['cover_image'] else None,
            'description': album['description'],
            'created_at': album['created_at'].isoformat(),
            'updated_at': album['updated_at'].isoformat(),
            'keywords': album['keywords'],
            'url': url_for('category', category=album['name'], _external=True),
            'images_api': url_for('get_images', category=album['name'], _external=True)
        }
        data.append(item)
    return Response(dumps(data), mimetype='application/json')


@app.route('/api/<category>/images', methods=['GET'])
def get_images(category):
    category = mongo.db.categories.find_one({'name': category})
    if category is None:
        return Response(dumps({'error': 'Category not found'}), mimetype='application/json'), 404

    images = mongo.db.images.find({'category_id': category['_id']})
    data = []
    for image in images:
        item = {
            'id': str(image['_id']),
            'filename': image['filename'],
            'description': image['description'],
            'uploaded_at': image['uploaded_at'].isoformat(),
            'compressed_url': url_for('serve_uploads', sub_path=category['name'] + '/compressed/' + image['filename'],
                                      _external=True),
            'original_url': url_for('serve_uploads', sub_path=category['name'] + '/original/' + image['filename'],
                                    _external=True)
        }
        data.append(item)
    return Response(dumps(data), mimetype='application/json')


if __name__ == '__main__':
    if os.getenv('ENVIRONMENT') == 'PRODUCTION':
        app.run(host='0.0.0.0', port=8000)
    else:
        app.run(debug=True)
