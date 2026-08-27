"""
Backfill Profiles Script
Reads all existing customers from the local agent DB and recalculates
RFM scores + segments from their purchase history.

Usage: python -m scripts.backfill_profiles
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import SessionLocal, init_db
from db.models import Customer
from db.queries import get_customer_purchases, update_customer_profile
from skills.profiler.scripts.rfm import calculate_rfm, assign_segment


def backfill():
    init_db()
    db = SessionLocal()

    try:
        customers = db.query(Customer).all()
        print(f"Backfilling {len(customers)} customers...")

        for customer in customers:
            purchases_orm = get_customer_purchases(db, customer.id)
            purchases = [
                {
                    "product_id": p.product_id,
                    "amount": p.amount,
                    "purchased_at": p.purchased_at,
                }
                for p in purchases_orm
            ]

            rfm = calculate_rfm(purchases)
            segment = assign_segment(rfm)

            churn_risk = (
                "high" if rfm["recency_days"] > 90
                else "medium" if rfm["recency_days"] > 45
                else "low"
            )

            update_customer_profile(
                db,
                customer.id,
                segment=segment,
                rfm_recency=rfm["recency_days"],
                rfm_frequency=rfm["frequency_count"],
                rfm_monetary=rfm["monetary_total"],
                churn_risk=churn_risk,
            )

            print(f"  {customer.id}: segment={segment} rfm={rfm['rfm_score']} churn={churn_risk}")

        print(f"\nBackfill complete: {len(customers)} customers updated.")

    finally:
        db.close()


if __name__ == "__main__":
    backfill()
