"""
FastAPI dependency injection helpers.
"""
from db.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends

__all__ = ["get_db"]
