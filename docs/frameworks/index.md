# Frameworks Overview

erdify recognizes five model frameworks from source and renders them into the
same ERD format. For the side-by-side framework comparison and the
detection/parsing table, see the [main README](../../README.md#-one-schema-five-frameworks).
This page shows a worked example with the generated PlantUML output; for
Django-specific details see [Django ORM](django.md).

## Example Models

Given these SQLModel definitions:

```python
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship

class UserRole(Enum):
    ADMIN = "admin"
    USER = "user"

class User(SQLModel, table=True):
    __tablename__: str = "user"

    id: int = Field(primary_key=True)
    name: str
    email: str = Field(index=True)
    role: UserRole = Field(default=UserRole.USER)

    orders: list["Order"] = Relationship(back_populates="user")

class Order(SQLModel, table=True):
    __tablename__: str = "order"

    id: int = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    total: float

    user: "User" = Relationship(back_populates="orders")
```

The tool generates:

![Example ERD Image](https://raw.githubusercontent.com/devsuit-berlin/erdify/main/example_erd.png "Example ERD Image")

with following code:

```plantuml
@startuml Database ERD
!define primary_key(x) <b><color:#b8861b><&key></color> x</b>
!define foreign_key(x) <color:#aaaaaa><&key></color> x
!define column(x) <color:#efefef><&media-record></color> x

skinparam linetype ortho

' Enums
enum UserRole << (E,#FFCC00) >> {
  ADMIN
  USER
}

' Entities
entity "user" as User {
  primary_key(id) : int
  column(name) : str
  column(email) : str
  column(role) : UserRole = USER
}

entity "order" as Order {
  primary_key(id) : int
  foreign_key(user_id) : int
  column(total) : float
}

' Relationships
Order }o--|| User : "user_id"

@enduml
```
