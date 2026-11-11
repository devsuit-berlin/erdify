"""Many-to-many through a Core Table: passed as an object and named by a string."""

from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


student_course = Table(
    "student_course",
    Base.metadata,
    Column("student_id", Integer, ForeignKey("student.id"), primary_key=True),
    Column("course_id", ForeignKey("course.id"), primary_key=True),
)


class Student(Base):
    __tablename__ = "student"

    id: Mapped[int] = mapped_column(primary_key=True)
    courses: Mapped[list["Course"]] = relationship(
        secondary=student_course, back_populates="students"
    )


class Course(Base):
    __tablename__ = "course"

    id: Mapped[int] = mapped_column(primary_key=True)
    students: Mapped[list["Student"]] = relationship(
        secondary="student_course", back_populates="courses"
    )
