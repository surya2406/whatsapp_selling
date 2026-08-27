import asyncio
import pandas as pd
from api.fetcher import get_meta_engine
from sqlalchemy import text

async def check():
    engine = get_meta_engine()
    async with engine.connect() as conn:
        res = await conn.execute(text('SELECT id, direction, sender, recipient FROM message'))
        rows = res.fetchall()
        print("Total rows in MySQL message table:", len(rows))
        for row in rows:
            print(f"ID: {row[0]}, Dir: {row[1]}, Sender: {row[2]}, Recipient: {row[3]}")

if __name__ == "__main__":
    asyncio.run(check())
