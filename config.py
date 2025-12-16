import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///cardwatch.db")
    MEDIA_ROOT = os.environ.get("MEDIA_ROOT", os.path.join(os.path.dirname(__file__), 'media'))
    CARDWATCH_DISABLE_SCHEDULER = os.environ.get("CARDWATCH_DISABLE_SCHEDULER")
    FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0")
