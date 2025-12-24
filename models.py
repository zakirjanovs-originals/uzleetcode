from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

# CRITICAL FIX: Import the single Base defined in database.py
from database import Base


# --- SQLAlchemy Models (Database Tables) ---

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)

    # Note: Added relationship for submissions
    submissions = relationship("Submission", backref="user", cascade="all, delete-orphan")


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True)
    title = Column(String)
    difficulty = Column(String)
    content = Column(Text)
    default_code = Column(Text, nullable=True)
    topic_tags_json = Column(Text, nullable=True)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    # Note: Using problem_slug instead of problem_id for simplicity (as seen in prior code)
    problem_slug = Column(String, index=True, nullable=False)

    code = Column(Text)
    language = Column(String, default="Python")  # Added back if missing
    status = Column(String, default="Pending")
    submitted_at = Column(DateTime, default=datetime.utcnow)
    analysis_json = Column(Text, default="{}")  # Added for storing results