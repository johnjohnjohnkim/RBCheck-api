from sqlalchemy.orm import Session
from datetime import datetime, time
from .. import models

def build_datetime_range(start_date, end_date=None):

    query_start = datetime.combine(start_date, time.min)
    if end_date is None:
        query_end = datetime.combine(start_date, time.max)
    else:
        query_end = datetime.combine(end_date, time.max)

    return query_start, query_end