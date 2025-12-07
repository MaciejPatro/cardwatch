import logging
from logging.handlers import RotatingFileHandler
import os

def configure_logging(app):
    if not app.debug:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        )

        file_handler = RotatingFileHandler('logs/cardwatch.log', maxBytes=10240, backupCount=10)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.INFO)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)

        logging.info('CardWatch startup')
    else:
        logging.basicConfig(level=logging.DEBUG)
