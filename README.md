# A simple Flask application for creating a portfolio of images.

## Description
This project is a Flask-based web application with MongoDB integration for handling image uploads and user authentication. It also includes a simple login system, image compression, and category management features.

## Installation and Setup
1. Clone the repository
   ```bash
   git clone https://github.com/MMikulec/flask_missartem.git
   ```

2. Change directory into the project folder
   ```bash
   cd your_project
   ```

3. Install the required Python packages
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `production.py` file for storing your MongoDB URI and other sensitive data

5. Configure uWSGI.ini as you need

5. Run the Flask app
   ```bash
   python app.py
   ```

## Usage
- To log in, navigate to `/login` and enter your username and password.
- Use `/upload` to upload images under a specified category.
- Manage categories and images via the application's UI.

## API Endpoints
- **GET /:** Fetches homepage with categories
- **POST /upload:** Uploads images to a specified category
- **POST /create_category:** Creates a new image category
- ...
