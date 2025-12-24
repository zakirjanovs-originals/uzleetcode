import os
import json
import time
import requests
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session
from typing import List

# --- CRITICAL FIX 1: Import Pydantic schemas from schemas.py ---
from schemas import SubmissionModel, AnalysisResponse

# Set the recommended stable model name
# NOTE: If this model still fails, try "gemini-1.5-flash"
MODEL_NAME = "gemini-2.5-flash"

# CRITICAL FIX 2: Load API key cleanly and use the placeholder
# The .strip() ensures no quotes or whitespace are included, which were causing the 400 Bad Request.
# NOTE: You MUST replace this placeholder with your actual key for the judge to work.
GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    "AIzaSyCaB1qe8Bnuq3TnCqAybAhnTQ3S0gnyZsE"
).strip().strip('"').strip("'")


# ---------------------------
# AI JUDGE FUNCTION
# ---------------------------

def call_gemini_api_structured(code: str, problem: str):
    """Calls Gemini API and requests JSON response based on Pydantic schema."""

    GEMINI_API_URL = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"
    )

    # Create generation schema
    schema = AnalysisResponse.model_json_schema()

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"""
You are an expert code judge. Analyze the provided Python code against the problem.

Problem:
{problem}

User's Code:
{code}

Analyze the solution and respond ONLY with a JSON object that strictly adheres to the provided schema.
The critique should assess correctness, efficiency, and adherence to Python best practices. Give the response in uzbek.
"""
                    }
                ]
            }
        ],
        # CRITICAL FIX 3: Changed "config" to the required "generationConfig"
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    # Retry logic (using exponential backoff)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(
                GEMINI_API_URL,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=45,
            )

            response.raise_for_status() # Raises HTTPError for 4xx/5xx responses
            result = response.json()

            if "candidates" not in result or not result["candidates"]:
                 # This happens if the model is blocked, or the response structure is unexpected
                raise KeyError("Missing candidates from API response. Check API key validity or safety settings.")

            # The JSON text is usually in the first candidate's first part
            json_text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(json_text)

        except requests.exceptions.HTTPError as http_err:
            # Handle 400 Bad Request (still likely an API key or configuration error)
            print(f"AI Judge Attempt {attempt + 1} failed: {http_err}")
            if attempt == max_retries - 1:
                return {
                    "status": "API_CALL_FAILED",
                    "timeComplexity": "Unknown",
                    "spaceComplexity": "Unknown",
                    "critique": f"API call failed after {max_retries} attempts. Check API Key and configuration: {http_err}",
                }
            time.sleep(2 ** attempt)

        except Exception as e:
            # Handle JSON parsing errors or general exceptions
            print(f"AI Judge Attempt {attempt + 1} failed (Parsing/Unknown): {e}")
            if attempt == max_retries - 1:
                return {
                    "status": "Error",
                    "timeComplexity": "Unknown",
                    "spaceComplexity": "Unknown",
                    "critique": f"AI Judge failed to process structured output: {str(e)}",
                }
            time.sleep(2 ** attempt)

    return None

# --- Router Definition ---

router = APIRouter()

@router.post("/judge")
async def judge_code(submission: SubmissionModel):
    problem_description = f"Problem Slug: {submission.problem}. The task is to solve this problem."

    analysis_result = call_gemini_api_structured(
        code=submission.code,
        problem=problem_description
    )

    if analysis_result and analysis_result.get('status') not in ['Error', 'API_CALL_FAILED']:
        return {
            "submission_status": "Processed",
            "analysis": analysis_result
        }
    else:
        # Pass the critique detail from the failed call
        critique_detail = analysis_result.get('critique', 'Unknown error') if analysis_result else 'Unknown error'
        raise HTTPException(
            status_code=500,
            detail=f"AI Judge failed to produce a valid analysis: {critique_detail}"
        )