"""The declarative base both modules share."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
