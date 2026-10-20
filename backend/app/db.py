import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, String, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA = Path(os.getenv('DATA_DIR', './data')).resolve()
for folder in ('originals', 'thumbnails', 'tmp'):
    (DATA / folder).mkdir(parents=True, exist_ok=True)
engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///' + str(DATA / 'media.db')))
Session = sessionmaker(engine, expire_on_commit=False)


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = 'media_assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))
    size: Mapped[int]
    original: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[str] = mapped_column(String(40), default=now, index=True)
    captured_at: Mapped[str | None] = mapped_column(String(40))
    date_source: Mapped[str | None] = mapped_column(String(30))
    width: Mapped[int | None]
    height: Mapped[int | None]
    duration: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    thumbnail: Mapped[str | None] = mapped_column(Text)
    pipeline_version: Mapped[str | None] = mapped_column(String(30))


class ImportItem(Base):
    __tablename__ = 'import_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey('media_assets.id'), index=True)
    filename: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[str] = mapped_column(String(40), default=now, index=True)
    duplicate: Mapped[bool]


def init_db():
    Base.metadata.create_all(engine)
