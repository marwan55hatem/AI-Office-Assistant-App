"""The repository base class: the first of the two tenant-isolation layers.

Every query a repository builds is filtered by the company id it was created with,
and every row it adds is stamped with that id. A repository can therefore not read or
change another company's data even when Row-Level Security is off (for example on a
superuser connection in development). RLS in PostgreSQL is the second layer.
"""
import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import Base

M = TypeVar("M", bound=Base)


class TenantRepository(Generic[M]):
    model: type[M]

    def __init__(self, session: Session, company_id: uuid.UUID):
        if company_id is None:
            raise ValueError("a tenant repository needs a company id")
        self.session = session
        self.company_id = company_id

    # -- queries -------------------------------------------------------------
    def query(self) -> Select:
        """``SELECT`` for this company's rows only; build every query from this."""
        return select(self.model).where(self.model.company_id == self.company_id)

    def get(self, row_id: Any) -> M | None:
        return self.session.scalars(self.query().where(self.model.id == row_id)).first()

    def list(self, *conditions, order_by=None, limit: int | None = None, offset: int = 0) -> list[M]:
        statement = self.query().where(*conditions)
        if order_by is not None:
            statement = statement.order_by(*order_by) if isinstance(order_by, tuple) else statement.order_by(order_by)
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        return list(self.session.scalars(statement))

    # -- writes --------------------------------------------------------------
    def add(self, **values) -> M:
        if values.get("company_id", self.company_id) != self.company_id:
            raise PermissionError("cannot write a row for another company")
        row = self.model(**{**values, "company_id": self.company_id})
        self.session.add(row)
        self.session.flush()
        return row

    def update(self, row: M, **values) -> M:
        if row.company_id != self.company_id or "company_id" in values:
            raise PermissionError("cannot change another company's row or move a row")
        for name, value in values.items():
            setattr(row, name, value)
        self.session.flush()
        return row

    def delete(self, row: M) -> None:
        if row.company_id != self.company_id:
            raise PermissionError("cannot delete another company's row")
        self.session.delete(row)
        self.session.flush()
