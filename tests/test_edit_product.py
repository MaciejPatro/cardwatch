import os
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# disable scheduler before importing app
os.environ["CARDWATCH_DISABLE_SCHEDULER"] = "1"

import app as cardapp
import db

class EditProductTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:', future=True)
        db.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        db.Base.metadata.create_all(engine)
        cardapp.app.config['TESTING'] = True
        self.client = cardapp.app.test_client()
        s = db.SessionLocal()
        try:
            s.add(db.Product(id=1, name='old', url='u', country='c'))
            s.commit()
        finally:
            s.close()

    def test_edit_updates_record(self):
        resp = self.client.post('/cardwatch/edit/1', data={'name': 'new', 'url': 'u2', 'country': 'c2'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        s = db.SessionLocal()
        try:
            p = s.get(db.Product, 1)
            self.assertEqual(p.name, 'new')
            self.assertEqual(p.url, 'u2')
            self.assertEqual(p.country, 'c2')
        finally:
            s.close()

if __name__ == '__main__':
    unittest.main()
