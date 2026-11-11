"""Association object: a mapped link class with a payload column and two many-to-ones."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)
    memberships: Mapped[list["Membership"]] = relationship(back_populates="player")


class Club(Base):
    __tablename__ = "club"

    id: Mapped[int] = mapped_column(primary_key=True)
    memberships: Mapped[list["Membership"]] = relationship(back_populates="club")


class Membership(Base):
    __tablename__ = "membership"

    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"), primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("club.id"), primary_key=True)
    since: Mapped[str]
    player: Mapped["Player"] = relationship(back_populates="memberships")
    club: Mapped["Club"] = relationship(back_populates="memberships")
