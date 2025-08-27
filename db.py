from datetime import datetime, date
from sqlalchemy import (create_engine, Column, Integer, String, Float, DateTime,
                        Date, ForeignKey, UniqueConstraint, func)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

ENGINE = create_engine("sqlite:///cardwatch.db", future=True)
SessionLocal = sessionmaker(bind=ENGINE, expire_on_commit=False, future=True)
Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # e.g., "Wings of the Captain Booster Box"
    url = Column(String, nullable=False, unique=True)
    country = Column(String, nullable=False)       # e.g., "Spain", "Germany", "Italy"
    is_enabled = Column(Integer, default=1)

    prices = relationship("Price", back_populates="product", cascade="all, delete-orphan")

class Price(Base):
    __tablename__ = "prices"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    low = Column(Float, nullable=False)            # lowest of the scraped 5
    avg5 = Column(Float, nullable=False)           # average of the scraped 5
    n_seen = Column(Integer, nullable=False)       # how many rows parsed (<=5)
    supply = Column(Integer, nullable=True)        # available items on site

    product = relationship("Product", back_populates="prices")

class Daily(Base):
    __tablename__ = "daily"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    day = Column(Date, default=date.today, index=True)
    low = Column(Float, nullable=False)
    avg = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint("product_id", "day", name="uniq_daily"),)

def init_db():
    Base.metadata.create_all(ENGINE)

def get_session():
    return SessionLocal()

def upsert_daily(session, product_id:int):
    # aggregate last 24h -> daily row
    today = date.today()
    agg = session.query(func.min(Price.low), func.avg(Price.avg5)).filter(
        Price.product_id == product_id,
        func.date(Price.ts) == today.isoformat()
    ).first()
    if agg and agg[0] is not None:
        low, avg = float(agg[0]), float(agg[1])
        row = session.query(Daily).filter_by(product_id=product_id, day=today).one_or_none()
        if row:
            row.low, row.avg = low, avg
        else:
            session.add(Daily(product_id=product_id, day=today, low=low, avg=avg))
        session.commit()
