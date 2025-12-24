from fastapi import FastAPI, Query, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func # NEW: Import func for database aggregation
from starlette.middleware.cors import CORSMiddleware
import requests
import json
import time
import os
from typing import List

# Import Database and Core SQLAlchemy Components
from database import Base, engine, SessionLocal, get_db

# Import SQLAlchemy Models (Database Tables)
from models import Problem, User, Submission

# Import Pydantic Schemas (FastAPI Data Contracts)
from schemas import UserCreate, SubmissionModel, AdminStatsResponse # NEW: Import AdminStatsResponse

# Import the judge router and function
from ai_judge import router as judge_router, call_gemini_api_structured

# Create database tables if they don't exist
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="UzLeetCode AI Judge API",
    description="A LeetCode-style platform backend with an AI code judge powered by Gemini.",
)

# --- Configuration ---
LEETCODE_GRAPHQL = "https://leetcode.com/graphql"
# Stable static endpoint for getting a list of all problem slugs
LEETCODE_STATIC_ALL = "https://leetcode.com/api/problems/all/"

# --- Admin Configuration ---
# NOTE: Replace this with an actual environment variable and store securely in a real app.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "supersecrettoken123")
ADMIN_USERNAME_DISPLAY = "UzLeetCode Admin"

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the AI Judge router (defined in ai_judge.py)
app.include_router(judge_router, prefix="/api")


# --- Utility Functions ---

def generate_user_id(username: str) -> str:
    """
    Generates a mock user ID for client-side use.
    In a real app, this would be a JWT or session token.
    """
    # Using a simple hash for demonstration
    return f"user_{hash(username) % 10000}"


# --- Admin Authentication Dependency ---
# FIX: Corrected dependency signature to use Query directly
def verify_admin_token(token: str = Query(alias="admin_token", default=None)):
    """Verifies a simple admin token passed as a query parameter."""
    if token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token.",
        )
    return True


# --- Admin Dashboard Endpoint ---
@app.get("/api/admin/stats", response_model=AdminStatsResponse, tags=["admin"])
def get_admin_dashboard_stats(is_admin: bool = Depends(verify_admin_token), db: Session = Depends(get_db)):
    """Retrieves all data necessary for the admin dashboard."""

    # 1. Total Users
    total_users = db.query(func.count(User.id)).scalar()

    # 2. Total Problems
    total_problems = db.query(func.count(Problem.id)).scalar()

    # 3. Total Submissions
    total_submissions = db.query(func.count(Submission.id)).scalar()

    # 4. Problems Solved Count (Distinct problems with at least one 'Passed' submission)
    problems_solved_count = db.query(func.count(Problem.slug)).join(Submission, Problem.slug == Submission.problem_slug).filter(
        Submission.status == "Passed"
    ).distinct().scalar() or 0

    # 5. Solved by Difficulty (Distinct problems with 'Passed' submission)
    easy_solved_count = db.query(func.count(Problem.slug)).join(Submission, Problem.slug == Submission.problem_slug).filter(
        Problem.difficulty == "Easy", Submission.status == "Passed"
    ).distinct().scalar() or 0

    medium_solved_count = db.query(func.count(Problem.slug)).join(Submission, Problem.slug == Submission.problem_slug).filter(
        Problem.difficulty == "Medium", Submission.status == "Passed"
    ).distinct().scalar() or 0

    hard_solved_count = db.query(func.count(Problem.slug)).join(Submission, Problem.slug == Submission.problem_slug).filter(
        Problem.difficulty == "Hard", Submission.status == "Passed"
    ).distinct().scalar() or 0

    return AdminStatsResponse(
        total_users=total_users or 0,
        total_problems=total_problems or 0,
        total_submissions=total_submissions or 0,
        problems_solved_count=problems_solved_count,
        easy_solved_count=easy_solved_count,
        medium_solved_count=medium_solved_count,
        hard_solved_count=hard_solved_count
    )

# --- User Endpoints (Authentication) ---

@app.post("/signup", response_model=UserCreate)
def signup_user(user_data: UserCreate, db: Session = Depends(get_db)):
    """Handles user registration."""
    db_user = db.query(User).filter(User.username == user_data.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # NOTE: In production, password MUST be hashed before storage!
    new_user = User(
        username=user_data.username,
        password=user_data.password,
        email=user_data.email,
        full_name=user_data.full_name
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Return a model with a redacted password field
    return UserCreate(
        username=new_user.username,
        password="[REDACTED]",
        email=new_user.email,
        full_name=new_user.full_name
    )


@app.post("/signin")
def signin_user(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Handles user sign-in and returns a mock user_id."""
    db_user = db.query(User).filter(User.username == form_data.username).first()

    # NOTE: In production, compare hashed passwords using a library like passlib!
    if not db_user or db_user.password != form_data.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Return a mock user ID and username to the client
    return {"user_id": generate_user_id(db_user.username), "username": db_user.username}


# --- Problem Data (LeetCode Scraping and Caching) ---

def fetch_all_problems_metadata():
    """
    Fetches a static, reliable list of problems (slug, title, difficulty)
    from the LeetCode API.
    """
    print("Fetching problem metadata from static endpoint...")
    response = requests.get(LEETCODE_STATIC_ALL, timeout=20)
    response.raise_for_status()
    data = response.json()

    problem_list = []
    # Data is structured under 'stat_status_pairs'
    for pair in data.get('stat_status_pairs', []):
        if pair.get('paid_only', False):
            continue  # Skip paid problems

        stat = pair['stat']
        difficulty_level = pair['difficulty']['level']

        # Map numeric difficulty to string (1: Easy, 2: Medium, 3: Hard)
        difficulty_map = {1: "Easy", 2: "Medium", 3: "Hard"}
        difficulty_str = difficulty_map.get(difficulty_level, "Unknown")

        problem_list.append({
            'titleSlug': stat['question__title_slug'],
            'title': stat['question__title'],
            'difficulty': difficulty_str,
            # topicTags are not available in this static list
            'topicTags': []
        })

    # NO LIMIT: Fetch all free problems (~2000+)
    return problem_list

# --- Translation Helper (Uzbek) ---
def translate_to_uzbek(text: str) -> str:
    """
    Uses Gemini to translate English problem content into Uzbek.
    Runs once and saved into DB.
    """
    try:
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{
                "parts": [{
                    "text": f"Translate this into Uzbek. Do NOT change formatting, do NOT add comments:\n\n{text}"
                }]
            }],
            "generationConfig": {
                "temperature": 0.3
            }
        }

        resp = requests.post(url, json=payload, timeout=40)
        resp.raise_for_status()
        data = resp.json()

        translated = data["candidates"][0]["content"]["parts"][0]["text"]
        return translated.strip()

    except Exception as e:
        print("Translation error:", e)
        return text  # fallback to English


def fetch_problem_details(title_slug: str):
    """Fetches the detailed content, topic tags, and default code snippet for a specific problem using GraphQL."""

    # GraphQL query
    query = """
query getQuestionDetail($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    content
    codeSnippets {
      lang
      code
    }
    topicTags {
      name
    }
  }
}
"""

    variables = {"titleSlug": title_slug}
    payload = {
        "operationName": "getQuestionDetail",
        "query": query,
        "variables": variables
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Origin": "https://leetcode.com"
    }

    response = requests.post(LEETCODE_GRAPHQL, json=payload, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise requests.exceptions.RequestException(f"GraphQL Errors: {data['errors']}")

    return data.get("data", {}).get("question", None)


@app.post("/cache-problems")
def cache_problems(db: Session = Depends(get_db)):
    """
    Fetches all free problems' metadata from LeetCode (static API) and caches basic info into the database.
    Details (content, code, tags) are fetched on-demand when a problem is selected.
    """

    try:
        # 1. Fetch the list of problems (metadata) using the stable static list
        problem_list = fetch_all_problems_metadata()
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch problem list from LeetCode API: {e}."
        )

    newly_cached_count = 0

    for item in problem_list:
        slug = item['titleSlug']

        # Check if problem already exists (by slug)
        if db.query(Problem).filter(Problem.slug == slug).first():
            continue

        # Cache only metadata; details fetched on-demand
        problem_data = {
            "slug": slug,
            "title": item['title'],
            "difficulty": item['difficulty'],
            "content": None,  # Placeholder: Will fetch on-demand
            "default_code": None,
            "topic_tags_json": None
        }

        new_problem = Problem(**problem_data)
        db.add(new_problem)
        newly_cached_count += 1

    db.commit()

    return {
        "message": f"Successfully cached metadata for {newly_cached_count} new problems. Details will be fetched on-demand when selected.",
        "total_cached": db.query(Problem).count()
    }


@app.get("/problems/")
def get_problem_list(db: Session = Depends(get_db)):
    """Returns a categorized list of all cached problems."""
    problems = db.query(Problem).all()

    categorized = {"Easy": [], "Medium": [], "Hard": []}

    for p in problems:
        problem_info = {
            "title": p.title,
            "slug": p.slug,
            "difficulty": p.difficulty,
            "topic_tags": json.loads(p.topic_tags_json) if p.topic_tags_json else []
        }

        if p.difficulty in categorized:
            categorized[p.difficulty].append(problem_info)

    return categorized


@app.get("/problem/{slug}")
async def get_problem_details(slug: str, db: Session = Depends(get_db)):
    """Returns details for a specific problem by slug. Fetches from LeetCode API if not cached."""
    problem = db.query(Problem).filter(Problem.slug == slug).first()

    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found. Run /cache-problems first.")

    # If details not cached (content is None), fetch and update
    if problem.content is None:
        try:
            detail = fetch_problem_details(slug)

            if detail:
                # Extract default code (Python preferred)
                default_code = "# No default code snippet available."
                for snippet in detail.get('codeSnippets', []):
                    if snippet['lang'] in ['Python', 'Python3']:
                        default_code = snippet['code']
                        break

                # Extract topic tags
                topic_tags_names = [tag['name'] for tag in detail.get('topicTags', [])]
                topic_tags_json = json.dumps(topic_tags_names)

                # Update the problem record
                english_content = detail.get('content', f"## {problem.title} - {problem.difficulty}\n\n[CONTENT UNAVAILABLE]")

                # --- NEW: Translate to Uzbek once ---
                uzbek_content = translate_to_uzbek(english_content)

                problem.content = uzbek_content

                problem.default_code = default_code
                problem.topic_tags_json = topic_tags_json

                db.commit()
                db.refresh(problem)

                # Small delay to simulate "searching/downloading" and avoid rapid requests
                time.sleep(1)  # Optional: Adjust or remove if not needed

            else:
                # Fallback if detail fetch fails
                problem.content = f"## {problem.title} - {problem.difficulty}\n\n[Unable to fetch content from LeetCode API.]"
                db.commit()

        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=503, detail=f"Failed to fetch problem details: {str(e)}")

    return {
        "title": problem.title,
        "content": problem.content,
        "difficulty": problem.difficulty,
        "default_code": problem.default_code,
        "topic_tags": json.loads(problem.topic_tags_json) if problem.topic_tags_json else []
    }


# --- My Account Endpoints (NEW) ---

@app.get("/api/my-account-stats/{username}")
def get_user_stats(username: str, db: Session = Depends(get_db)):
    """
    Retrieves user statistics: total submissions and unique problems solved.
    The frontend should pass the actual username (from localStorage) here.
    """
    db_user = db.query(User).filter(User.username == username).first()

    if not db_user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found.")

    # Total Submissions
    total_submissions = db.query(Submission).filter(Submission.user_id == db_user.id).count()

    # Unique Problems Solved (status == 'Passed')
    solved_slugs = (
        db.query(Submission.problem_slug)
        .filter(
            Submission.user_id == db_user.id,
            Submission.status == "Passed"
        )
        .distinct()
        .all()
    )
    unique_solved_count = len(solved_slugs)

    # Recent Submissions (Limited to last 20)
    submissions = (
        db.query(Submission)
        .filter(Submission.user_id == db_user.id)
        .order_by(Submission.submitted_at.desc())
        .limit(20)
        .all()
    )

    # Format submissions for response
    submission_list = []
    for sub in submissions:
        # Fetch problem title for display
        problem = db.query(Problem).filter(Problem.slug == sub.problem_slug).first()
        submission_list.append({
            "id": sub.id,
            "problem_title": problem.title if problem else sub.problem_slug,
            "status": sub.status,
            "submitted_at": sub.submitted_at.isoformat(),
        })

    return {
        "username": db_user.username,
        "full_name": db_user.full_name,
        "email": db_user.email,
        "total_submissions": total_submissions,
        "problems_solved_count": unique_solved_count,
        "recent_submissions": submission_list
    }


# --- About Us Endpoint (NEW) ---
@app.get("/api/about")
def get_about_info():
    """Simple endpoint for About Us data."""
    return {
        "project_name": "UzLeetCode AI Judge",
        "description": "An automated coding platform leveraging the Gemini API for intelligent code critique and judging, inspired by LeetCode.",
        "author": "Your Name/Team",
        "copyright": "All rights reserved UzLeetCode 2025"
    }


# --- Submission Endpoints ---

@app.post("/api/submit")
async def create_submission(submission: SubmissionModel, db: Session = Depends(get_db)):
    """
    Handles user code submission, saves it to the DB, and triggers the AI Judge.
    """

    # NOTE: You must have at least one user registered via /signup for this to work.
    # We fetch the first user as a placeholder for the authenticated user.
    authenticated_user = db.query(User).first()
    if not authenticated_user:
        raise HTTPException(status_code=401, detail="No users registered. Please sign up first.")

    # Check if the problem exists in the cache
    problem_data = db.query(Problem).filter(Problem.slug == submission.problem).first()
    if not problem_data:
        raise HTTPException(status_code=404, detail=f"Problem '{submission.problem}' not found in cache.")

    # 1. Save the submission to the database
    new_submission = Submission(
        user_id=authenticated_user.id,  # Using the ID of the first registered user
        problem_slug=submission.problem,
        code=submission.code,
        status="Pending",  # Initial status
        analysis_json="{}"
    )
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)

    try:
        # 2. Call the AI Judge function directly (from ai_judge.py)

        # Prepare a descriptive prompt for the AI Judge
        problem_description = f"Problem Title: {problem_data.title}\nDifficulty: {problem_data.difficulty}\nContent: {problem_data.content[:500]}..."  # Limit content length

        analysis_result = call_gemini_api_structured(
            code=submission.code,
            problem=problem_description
        )

        # 3. Update the submission record with the result
        if analysis_result and analysis_result.get('status') not in ['Error', 'API_KEY_ERROR', 'API_CALL_FAILED']:
            new_submission.status = analysis_result.get('status', 'Unknown')
            new_submission.analysis_json = json.dumps(analysis_result)
            db.commit()

            return {
                "message": "Submission processed successfully.",
                "submission_id": new_submission.id,
                "status": new_submission.status,
                "analysis": analysis_result
            }
        else:
            # Handle error from the AI Judge itself
            error_critique = analysis_result.get('critique', 'AI Judge returned an unknown error.')
            new_submission.status = "Failed"
            new_submission.analysis_json = json.dumps(analysis_result)
            db.commit()

            # Set status code based on analysis result status
            status_code = 500
            if analysis_result and analysis_result.get('status') == 'API_KEY_ERROR':
                 status_code = 401 # Unauthorized/Missing Credentials

            raise HTTPException(
                status_code=status_code,
                detail=f"AI Judge failed to produce a valid analysis: {error_critique}"
            )

    except Exception as e:
        # Log and update status if the judge call fails unexpectedly (e.g., network error)
        new_submission.status = "System Error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during judging: {str(e)}")


@app.get("/api/submissions/{submission_id}")
def get_submission_result(submission_id: int, db: Session = Depends(get_db)):
    """Retrieves the full result of a specific submission."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found.")

    return {
        "id": submission.id,
        "problem_slug": submission.problem_slug,
        "status": submission.status,
        "code": submission.code,
        "created_at": submission.submitted_at.isoformat(),
        "analysis": json.loads(submission.analysis_json) if submission.analysis_json else {}
    }


# --- Root Endpoint ---

@app.get("/", response_class=HTMLResponse)
def root():
    return {"status": "ok"}
async def serve_root():
    """Reads and serves the index.html file."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Frontend file (index.html) not found.</h1><p>Please ensure 'index.html' is in the same directory as 'main.py'.</p>",
            status_code=404
        )

# --- Admin Dashboard Endpoint ---
@app.get("/api/admin/stats", response_model=AdminStatsResponse, tags=["admin"])
def get_admin_dashboard_stats(is_admin: bool = Depends(verify_admin_token), db: Session = Depends(get_db)):
    """Retrieves all data necessary for the admin dashboard."""

    # 1. Total Users
    total_users = db.query(func.count(User.id)).scalar()

    # ... (other queries for Problems, Submissions, and Solved Counts) ...

    return AdminStatsResponse(
        total_users=total_users or 0,
        total_problems=total_problems or 0,
        total_submissions=total_submissions or 0,
        # ... (solved counts by difficulty) ...

    )

