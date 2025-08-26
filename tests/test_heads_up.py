import unittest
from datetime import date, timedelta, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base, Product, Daily, Price
from scraper import is_heads_up

class HeadsUpTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, future=True)

    def test_averages_last_seven_days(self):
        s = self.Session()
        try:
            # product needed for foreign keys
            s.add(Product(id=1, name='p', url='u', country='c'))
            today = date.today()
            # create 10 days of daily rows: recent 7 with avg=100, earlier 3 with avg=200
            for i in range(10):
                day = today - timedelta(days=i)
                avg = 100.0 if i < 7 else 200.0
                s.add(Daily(product_id=1, day=day, low=avg, avg=avg))
            # latest hourly price
            s.add(Price(product_id=1, low=90.0, avg5=90.0, n_seen=5, ts=datetime.utcnow()))
            s.commit()

            heads, now_low, avg7 = is_heads_up(s, 1)
            self.assertAlmostEqual(avg7, 100.0)
            self.assertTrue(heads)
        finally:
            s.close()

if __name__ == '__main__':
    unittest.main()
