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


def test_uploads_use_unique_filenames(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_flask, "MEDIA_ROOT", tmp_path)
    upload = tmp_path / "item_images"
    monkeypatch.setattr(tracker_flask, "UPLOAD_FOLDER", upload)

    cardapp.app.config["TESTING"] = True
    client = cardapp.app.test_client()

    data1 = {
        "name": "item1",
        "buy_date": "2024-01-01",
        "price": "1",
        "currency": "CHF",
        "image": (io.BytesIO(b"a"), "same.jpg"),
    }
    resp1 = client.post("/tracker/add", data=data1, content_type="multipart/form-data")
    assert resp1.status_code == 302

    data2 = {
        "name": "item2",
        "buy_date": "2024-01-02",
        "price": "1",
        "currency": "CHF",
        "image": (io.BytesIO(b"b"), "same.jpg"),
    }
    resp2 = client.post("/tracker/add", data=data2, content_type="multipart/form-data")
    assert resp2.status_code == 302

    s = db.SessionLocal()
    items = s.query(db.Item).order_by(db.Item.id).all()
    s.close()

    assert len(items) == 2
    assert items[0].image != items[1].image
    assert (tmp_path / items[0].image).exists()
    assert (tmp_path / items[1].image).exists()

