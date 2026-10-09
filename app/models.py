"""
Initializes PostgreSQL tables with ORM
"""

from .database import Base
from sqlalchemy import JSON, Column, Date, Integer, Numeric, String, Boolean, ForeignKey
from sqlalchemy.sql.expression import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import TIMESTAMP

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(Integer, primary_key = True)
    transaction_datetime = Column(TIMESTAMP(timezone = True), nullable = False)
    amount = Column(Numeric(precision=10, scale=2))
    place = Column(String)
    transaction_type = Column(String, nullable = False)

class DailyDigest(Base):
    """One computed summary per local calendar day; see services/insights.py."""
    __tablename__ = "daily_digests"

    day = Column(Date, primary_key = True)
    computed_at = Column(TIMESTAMP(timezone = True), nullable = False)
    payload = Column(JSON().with_variant(JSONB(), "postgresql"), nullable = False)
