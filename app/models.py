"""
Initializes PostgreSQL tables with ORM
"""

from .database import Base
from sqlalchemy import Column, Integer, Numeric, String, Boolean, ForeignKey
from sqlalchemy.sql.expression import text
from sqlalchemy.sql.sqltypes import TIMESTAMP

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(Integer, primary_key = True)
    transaction_datetime = Column(TIMESTAMP(timezone = True), nullable = False)
    amount = Column(Numeric(precision=10, scale=2))
    place = Column(String)
    transaction_type = Column(String, nullable = False)