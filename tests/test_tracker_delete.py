import os
from datetime import date

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db
import tracker_flask


os.environ["CARDWATCH_DISABLE_SCHEDULER"] = "1"


def create_app():
    engine = create_engine("sqlite:///:memory:", future=True)
    db.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db.Base.metadata.create_all(engine)

    app = Flask(__name__, template_folder="../templates")
    app.secret_key = "test"
    app.register_blueprint(tracker_flask.tracker_bp)
    app.add_url_rule("/", "home", lambda: "")
    app.add_url_rule("/cardwatch", "index", lambda: "")
    return app


def test_delete_removes_item_and_shows_in_edit():
    app = create_app()
    client = app.test_client()

    session = db.SessionLocal()
    try:
        item = db.Item(
            name="DeleteMe",
            buy_date=date.today(),
            graded=0,
            price=1.0,
            currency="USD",
        )
        session.add(item)
        session.commit()
        item_id = item.id
    finally:
        session.close()

    resp = client.get("/tracker/")
    assert resp.status_code == 200
    assert f"/tracker/delete/{item_id}" not in resp.get_data(as_text=True)

    resp = client.get(f"/tracker/edit/{item_id}")
    assert resp.status_code == 200
    assert f"/tracker/delete/{item_id}" in resp.get_data(as_text=True)

    resp = client.post(f"/tracker/delete/{item_id}", follow_redirects=True)
    assert resp.status_code == 200

    session = db.SessionLocal()
    try:
        assert session.get(db.Item, item_id) is None
    finally:
        session.close()

