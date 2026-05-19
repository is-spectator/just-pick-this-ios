from collections.abc import Iterator
from typing import Any

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


convention: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


def make_engine(**kwargs: Any):
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required to create a database engine.")
    return create_engine(str(settings.database_url), pool_pre_ping=True, **kwargs)


def make_session_factory(**kwargs: Any) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(), autoflush=False, autocommit=False, **kwargs)


def get_db_session() -> Iterator[Session]:
    session_factory = make_session_factory()
    with session_factory() as session:
        yield session
