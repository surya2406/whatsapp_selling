import asyncio
from sqlalchemy import text
from api.fetcher import get_meta_engine

async def check():
    engine = get_meta_engine()
    async with engine.connect() as conn:
        try:
            res = await conn.execute(text('SELECT id, is_processed FROM message LIMIT 5'))
            print("is_processed exists. First 5 rows:", res.fetchall())
            res = await conn.execute(text('SELECT COUNT(*) FROM message WHERE is_processed = 0'))
            print("Rows with is_processed = 0:", res.scalar())
        except Exception as e:
            print("is_processed does not exist:", e)

if __name__ == "__main__":
    asyncio.run(check())
