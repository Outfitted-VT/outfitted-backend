# Import every model here so Base.metadata knows about it.
# Alembic imports this package to autogenerate migrations.
from app.db.base import Base

__all__ = ["Base"]
