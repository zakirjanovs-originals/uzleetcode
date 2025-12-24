from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict

# --- Core Schemas ---

class ProblemBase(BaseModel):
    """Schema for basic problem information."""
    title: str
    slug: str
    difficulty: str

class AnalysisResponse(BaseModel):
    """Schema for structured AI Judge output."""
    status: str
    timeComplexity: str
    spaceComplexity: str
    critique: str

class SubmissionModel(BaseModel):
    """Schema for a code submission sent by the user."""
    code: str
    problem: str  # problem slug

# --- User/Auth Schemas ---

class UserBase(BaseModel):
    """Base schema for user data."""
    username: str
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None

class UserCreate(BaseModel):
    """Schema for user registration data."""
    username: str
    password: str # NOTE: Password should be hashed client-side in production
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    """Schema for user sign-in data (used by FastAPI security)."""
    username: str
    password: str

class TokenResponse(BaseModel):
    """Schema for the JWT/mock token response."""
    access_token: str
    token_type: str = "bearer"
    username: str
    full_name: Optional[str] = None

# --- Admin Dashboard Schema ---
class AdminStatsResponse(BaseModel):
    """Schema for Admin Dashboard statistics (used by /api/admin/stats)."""
    total_users: int
    total_problems: int
    total_submissions: int
    problems_solved_count: int
    easy_solved_count: int
    medium_solved_count: int
    hard_solved_count: int

# --- Submission Detail Schema ---
class SubmissionResult(BaseModel):
    """Schema for retrieving a full submission result."""
    id: int
    problem_slug: str
    status: str
    code: str
    created_at: str # ISO 8601 string from submission.submitted_at.isoformat()
    analysis: Dict # Matches the json.loads(submission.analysis_json) return

# --- User Stats Schemas ---
class RecentSubmission(BaseModel):
    """Schema for a single recent submission, used within UserStatsResponse."""
    problem_title: str
    status: str
    submitted_at: str # ISO 8601 string

class UserStatsResponse(BaseModel):
    """
    Schema for the user account statistics response,
    matching the data structure used by index.html for the account dashboard.
    """
    username: str
    full_name: Optional[str] = None
    email: EmailStr
    total_submissions: int
    problems_solved_count: int
    recent_submissions: List[RecentSubmission]