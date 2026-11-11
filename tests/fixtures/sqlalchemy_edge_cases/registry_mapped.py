"""Classes mapped with the @registry.mapped decorator instead of a declarative base."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, registry, relationship

mapper_registry = registry()


@mapper_registry.mapped
class Garden:
    __tablename__ = "garden"

    id: Mapped[int] = mapped_column(primary_key=True)
    plants: Mapped[list["Plant"]] = relationship(back_populates="garden")


@mapper_registry.mapped
class Plant:
    __tablename__ = "plant"

    id: Mapped[int] = mapped_column(primary_key=True)
    species: Mapped[str | None]
    garden_id: Mapped[int] = mapped_column(ForeignKey("garden.id"))
    garden: Mapped["Garden"] = relationship(back_populates="plants")
