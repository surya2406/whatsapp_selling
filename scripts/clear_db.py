import asyncio
from sqlalchemy import text
from db.database import SessionLocal

async def clear():
    async with SessionLocal() as db:
        # Delete from child tables first to avoid foreign key constraints (if enforced)
        await db.execute(text('DELETE FROM review_drafts'))
        await db.execute(text('DELETE FROM conversation_messages'))
        await db.execute(text('DELETE FROM agent_responses'))
        await db.execute(text('DELETE FROM recommendations'))
        await db.execute(text('DELETE FROM purchases'))
        # Delete from parent tables
        await db.execute(text('DELETE FROM customers'))
        await db.execute(text('DELETE FROM processing_batches'))
        await db.commit()
        print("Cleared ALL local tables completely! Fresh start ready.")

if __name__ == "__main__":
    asyncio.run(clear())
