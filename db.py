from datetime import datetime, date
from contextlib import contextmanager
from typing import Generator, Optional, Any
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Date,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from config import Config

ENGINE = create_engine(Config.SQLALCHEMY_DATABASE_URI, future=True)
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


class SingleCard(Base):
    __tablename__ = "single_cards"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False, unique=True)
    language = Column(String, nullable=False)  # English or Japanese
    condition = Column(String, nullable=False, default="Mint or Near Mint")  # Mint or Near Mint
    image_url = Column(String, nullable=True)
    is_enabled = Column(Integer, default=1)
    category = Column(String, nullable=True)
    game = Column(String, nullable=True, default="One Piece")
    set_name = Column(String, nullable=True)
    product_id = Column(Integer, nullable=True, unique=True, index=True)

    prices = relationship(
        "SingleCardPrice", back_populates="card", cascade="all, delete-orphan"
    )

    offers = relationship(
        "SingleCardOffer", back_populates="card", cascade="all, delete-orphan"
    )

    psa10_prices = relationship(
        "PSA10Price", back_populates="card", cascade="all, delete-orphan"
    )

    psa10_offers = relationship(
        "PSA10Offer", back_populates="card", cascade="all, delete-orphan"
    )


class SingleCardPrice(Base):
    __tablename__ = "single_card_prices"

    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("single_cards.id"), index=True, nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, index=True)

    low = Column(Float, nullable=True)  # lowest of the scraped 5 (filtered)
    avg5 = Column(Float, nullable=True)  # average of the scraped 5 (filtered)
    n_seen = Column(Integer, nullable=True)  # number of rows parsed (<=5)
    supply = Column(Integer, nullable=True)

    from_price = Column(Float, nullable=True)
    price_trend = Column(Float, nullable=True)
    avg7_price = Column(Float, nullable=True)
    avg1_price = Column(Float, nullable=True)

    card = relationship("SingleCard", back_populates="prices")


class SingleCardOffer(Base):
    __tablename__ = "single_card_offers"

    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("single_cards.id"), index=True, nullable=False)
    seller_name = Column(String, nullable=False)
    country = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, index=True)

    card = relationship("SingleCard", back_populates="offers")


class SingleCardDaily(Base):
    __tablename__ = "single_card_daily"
    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("single_cards.id"), index=True, nullable=False)
    day = Column(Date, default=date.today, index=True)
    low = Column(Float, nullable=True)
    avg = Column(Float, nullable=True)
    __table_args__ = (UniqueConstraint("card_id", "day", name="uniq_single_daily"),)


class Item(Base):
    """Inventory items tracked by the old Django app."""
    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    buy_date = Column(Date, nullable=False)
    link = Column(String, nullable=True)
    graded = Column(Integer, default=0)
    price = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)
    sell_price = Column(Float, nullable=True)
    sell_date = Column(Date, nullable=True)
    image = Column(String, nullable=True)
    not_for_sale = Column(Integer, default=0)
    category = Column(String, default="Active")
    card_id = Column(Integer, nullable=True)
    
    # Old columns for Invoice Parsing (Deprecated, moving to BookkeepingItem)
    # extra_costs = Column(Float, nullable=False, default=0.0)
    # external_id = Column(String, nullable=True) 
    # bookkeeping_id = Column(Integer, ForeignKey("bookkeeping_entries.id"), nullable=True)
    
    # bookkeeping_entry = relationship("BookkeepingEntry", backref="items")


class PSA10Price(Base):
    __tablename__ = "psa10_prices"
    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("single_cards.id"), index=True, nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    low = Column(Float, nullable=False) # Lowest PSA10 price found

    card = relationship("SingleCard", back_populates="psa10_prices")


class PSA10Offer(Base):
    __tablename__ = "psa10_offers"
    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("single_cards.id"), index=True, nullable=False)
    seller_name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    comment = Column(String, nullable=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)

    card = relationship("SingleCard", back_populates="psa10_offers")


class BookkeepingEntry(Base):
    __tablename__ = "bookkeeping_entries"
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, default=date.today)
    entry_type = Column(String, nullable=False) # 'cost', 'gain'
    description = Column(String, nullable=True)
    
    amount_eur = Column(Float, nullable=False, default=0.0)
    amount_chf = Column(Float, nullable=False, default=0.0)
    original_currency = Column(String, nullable=False, default='EUR') # 'EUR', 'CHF'
    exchange_rate = Column(Float, nullable=False, default=1.0)
    
    file_path = Column(String, nullable=True) # Relative path to storage
    
    is_private_collection = Column(Integer, default=0) # 0 or 1
    market_value = Column(Float, nullable=True)
    
    needs_import_declaration = Column(Integer, default=0) # 0 or 1
    import_declaration_filed = Column(Integer, default=0) # 0 or 1
    
    cost_type = Column(String, nullable=True) # 'shipping', 'misc', 'purchase', 'import', 'private_collection', 'sale'
    has_vat = Column(Integer, default=1) # 1=Yes, 0=No (Warning if Purchase and 0)
    vat_rate = Column(Float, default=0.0) 
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    items = relationship("BookkeepingItem", backref="entry", cascade="all, delete-orphan")
    
    # Declarations made FOR this entry (Purchase -> Declaration)
    # This entry is the SOURCE.
    declarations = relationship(
        "EntryLink",
        foreign_keys="[EntryLink.source_id]",
        back_populates="source",
        cascade="all, delete-orphan"
    )
    
    # Purchases associated WITH this entry (Declaration -> Purchases)
    # This entry is the TARGET.
    associated_purchases = relationship(
        "EntryLink",
        foreign_keys="[EntryLink.target_id]",
        back_populates="target",
        cascade="all, delete-orphan"
    )

    attachments = relationship(
        "BookkeepingAttachment",
        back_populates="entry",
        cascade="all, delete-orphan"
    )


class BookkeepingItem(Base):
    """Inventory items specifically for Bookkeeping (financial stock)."""
    __tablename__ = "bookkeeping_items"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    
    price = Column(Float, nullable=False, default=0.0) # Line Item Price
    extra_costs = Column(Float, nullable=False, default=0.0) # Allocated Ship/Tax
    currency = Column(String, nullable=False, default='EUR')
    
    external_id = Column(String, nullable=True) # e.g. Cardmarket Order ID
    
    bookkeeping_id = Column(Integer, ForeignKey("bookkeeping_entries.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "extra": self.extra_costs, # 'extra' per JS expectations? In JS I saw 'extra' and 'price'.
            # Let's check JS. JS uses 'item.extra' and 'item.price'.
            "extra_costs": self.extra_costs, # sending both just in case
            "currency": self.currency,
            "external_id": self.external_id
        }

class EntryLink(Base):
    """
    Many-to-Many link between Bookkeeping Entries.
    Usage: Linking Purchase Entry (Source) -> Declaration Cost Entry (Target).
    """
    __tablename__ = "entry_links"
    
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("bookkeeping_entries.id"), nullable=False, index=True)
    target_id = Column(Integer, ForeignKey("bookkeeping_entries.id"), nullable=False, index=True)
    link_type = Column(String, default="declaration") # 'declaration', 'refund', etc.
    amount = Column(Float, nullable=True, default=0.0) # Distributed amount if applicable
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    source = relationship("BookkeepingEntry", foreign_keys=[source_id], back_populates="declarations")
    target = relationship("BookkeepingEntry", foreign_keys=[target_id], back_populates="associated_purchases")

# Add relationships to BookkeepingEntry (Monkey-patching not ideal, better to edit class above)
# But since we are replacing content, let's edit the class above.



def init_db():
    Base.metadata.create_all(ENGINE)


from contextlib import contextmanager
from typing import Generator, Optional

# ... (keep existing imports)

@contextmanager
def get_db_session() -> Generator:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_session():
    """Deprecated: Use get_db_session context manager instead."""
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


def upsert_single_daily(session, card_id: int):
    """Aggregate the most recent day's single-card prices."""
    today = date.today()
    agg = (
        session.query(func.min(SingleCardPrice.low), func.avg(SingleCardPrice.avg5))
        .filter(SingleCardPrice.card_id == card_id, func.date(SingleCardPrice.ts) == today)
        .first()
    )
    if agg and agg[0] is not None:
        low, avg = float(agg[0]), float(agg[1]) if agg[1] is not None else None
        row = (
            session.query(SingleCardDaily)
            .filter_by(card_id=card_id, day=today)
            .one_or_none()
        )
        if row:
            row.low, row.avg = low, avg
        else:
            session.add(SingleCardDaily(card_id=card_id, day=today, low=low, avg=avg))
        session.commit()


class BookkeepingAttachment(Base):
    __tablename__ = "bookkeeping_attachments"
    
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("bookkeeping_entries.id"), nullable=False, index=True)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    entry = relationship("BookkeepingEntry", back_populates="attachments")

class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    date = Column(Date, primary_key=True)
    currency = Column(String, default="EUR")
    rate = Column(Float, nullable=False) # CHF per 1 Unit

