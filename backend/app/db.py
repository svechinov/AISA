from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# pool_pre_ping: recover stale connections. connect_timeout: fail fast if DB is unreachable (Docker race).
_db_url = settings.DATABASE_URL or ""
_connect_args = {}
if _db_url.startswith("postgresql"):
    _connect_args["connect_timeout"] = 15

engine = create_engine(
    settings.DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
