from flask import Flask
from models import db
from config import Config
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI  # Or any other DB
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.secret_key = 'your-secret-key-change-this-in-production'  # Change this in production!
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
    CORS(app)
    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app
