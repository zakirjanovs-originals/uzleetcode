from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from fastapi import Depends
from sqlalchemy.orm import Session

# Define the declarative base here so it is the single source for all models
Base = declarative_base()

DATABASE_URL = "sqlite:///./uzleetcode.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- DB session dependency (Moved here for better modularity) ---
def get_db():
    """Provides a database session for request handling."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()