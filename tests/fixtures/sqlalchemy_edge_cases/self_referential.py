"""Self-referential adjacency list: parent / children with remote_side."""

from typing import List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Node(Base):
    __tablename__ = "node"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("node.id"))
    parent: Mapped[Optional["Node"]] = relationship(back_populates="children", remote_side=[id])
    children: Mapped[List["Node"]] = relationship(back_populates="parent")
