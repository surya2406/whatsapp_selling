"""
Database connection and session setup using SQLAlchemy (Async).
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from config.settings import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding an async DB session."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables on application startup."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate purchases table if missing columns in existing SQLite DB
        try:
            res = await conn.execute(text("PRAGMA table_info(purchases)"))
            cols = {row[1] for row in res.fetchall()}
            if cols:
                if "order_id" not in cols:
                    await conn.execute(text("ALTER TABLE purchases ADD COLUMN order_id VARCHAR(50)"))
                if "quantity" not in cols:
                    await conn.execute(text("ALTER TABLE purchases ADD COLUMN quantity INTEGER DEFAULT 1"))
                if "unit_price" not in cols:
                    await conn.execute(text("ALTER TABLE purchases ADD COLUMN unit_price FLOAT DEFAULT 0.0"))
        except Exception:
            pass

