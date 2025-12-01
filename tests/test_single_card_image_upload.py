import io
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# disable scheduler before importing app
os.environ["CARDWATCH_DISABLE_SCHEDULER"] = "1"

import app as cardapp
import tracker_flask
import db


def setup_function(_):
    engine = create_engine("sqlite:///:memory:", future=True)
    db.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db.Base.metadata.create_all(engine)


def test_single_card_upload_uses_unique_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_flask, "MEDIA_ROOT", tmp_path)
    upload = tmp_path / "single_card_images"
    monkeypatch.setattr(cardapp, "SINGLE_CARD_UPLOAD_FOLDER", upload)

    cardapp.app.config["TESTING"] = True
    client = cardapp.app.test_client()

    data1 = {
        "name": "card1",
        "url": "https://cardmarket.example/1",
        "language": "English",
        "image": (io.BytesIO(b"a"), "photo.jpg"),
    }

    resp1 = client.post(
        "/cardwatch/singles/add", data=data1, content_type="multipart/form-data"
    )
    assert resp1.status_code == 302

    data2 = {
        "name": "card2",
        "url": "https://cardmarket.example/2",
        "language": "English",
        "image": (io.BytesIO(b"b"), "photo.jpg"),
    }

    resp2 = client.post(
        "/cardwatch/singles/add", data=data2, content_type="multipart/form-data"
    )
    assert resp2.status_code == 302

    s = db.SessionLocal()
    cards = s.query(db.SingleCard).order_by(db.SingleCard.id).all()
    s.close()

    assert len(cards) == 2
    assert cards[0].image_url != cards[1].image_url
    assert (tmp_path / cards[0].image_url).exists()
    assert (tmp_path / cards[1].image_url).exists()
