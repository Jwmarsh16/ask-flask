# server/config.py
# Serve the built React app from ../client/dist 

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from flask_restful import Api
from flask_cors import CORS
from dotenv import load_dotenv
import os

load_dotenv()  # load .env for local dev

# Naming conventions for Alembic
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=naming_convention)

app = Flask(
    __name__,
    static_url_path='',                                      # serve assets at root
    static_folder=os.path.join('..', 'client', 'dist'),
    template_folder=os.path.join('..', 'client', 'dist'),
)

app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Fallback DB so the app always boots locally
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URI",
    "sqlite:///instance/app.db"                              # use instance/app.db if unset
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app=app, metadata=metadata)
migrate = Migrate(app=app, db=db)
bcrypt = Bcrypt(app=app)
api = Api(app=app)

# CORS:
# In production (single service), FE and BE share the same origin → CORS not required,
# but keeping localhost origins helps during dev if you run Vite separately.
frontend_origin = os.getenv("FRONTEND_ORIGIN")               # e.g., http://localhost:5173
origins = [
    "http://localhost:4000",
    "http://localhost:5173",
    "http://127.0.0.1:4000",
    "http://127.0.0.1:5173",
]
if frontend_origin:
    origins.append(frontend_origin)

CORS(app, supports_credentials=True, origins=origins)
