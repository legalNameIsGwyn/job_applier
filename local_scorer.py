"""
Local Job Scorer - Scores job postings against a resume using local Ollama models.
No cloud APIs needed.
"""

import json
import ollama
from pathlib import Path
import re

RESUME_FILE = r"C:\Users\Gwyn\Desktop\Projects\job_scraper\resume.json"


def load_resume():
    """Load resume data from JSON file."""
    with open(RESUME_FILE, "r") as f:
        return json.load(f)


def score_job(job_title: str, company: str, location: str, description: str) -> dict:
    """
    Score a job against the resume using Ollama.
    Returns: {"match_score": 0-100, "matched_skills": [], "key_gaps": []}
    """
    resume = load_resume()

    prompt = f"""
        You are a hiring manager reviewing applications for ENTRY-LEVEL positions only. I have my resume and a job posting. 

        Resume summary (extracted facts ONLY - do NOT invent experience):
        - Name: {resume.get('name', '')}
        - Location: {resume.get('contact', {}).get('location', 'Remote')}
        - Skills from resume: {', '.join(resume.get('skills', []))}
        - Experience: {len(resume.get('experience', []))} roles ({'Associate' in str(resume.get('summary', '')) or 'Junior' in str(resume.get('summary', ''))})

        IMPORTANT: This is an ENTRY-LEVEL job search. Your match score should reflect whether my skills and ANY actual experience make me suitable for junior/entry-level roles, not senior positions.

        Job title: {job_title}
        Company: {company}
        Location: {location}
        Description: {description[:2000]}

        Rate your match on a scale of 1-10. Provide:
        - A numeric score (1-10) - lower is ok for entry-level roles if skills match
        - Which skills from my resume match this job (list them)
        - Score 5-9: Associate/Junior roles qualify with relevant skills even at 5
        - Any significant gaps I have compared to the job requirements

        Respond in strict JSON format only:"""

    response = ollama.chat(
        model="deepseek-r1:7b",
        messages=[{"role": "user", "content": prompt}]
    )

    content = response.message.content.strip()
    # Extract JSON from response (Ollama may wrap it in code blocks)
    json_match = re.search(r"```json\s*({.*?})\s*```", content, re.DOTALL)
    
    if not json_match:
        json_match = re.search(r"({.*?})", content, re.DOTALL)

    if json_match:
        score_data = json.loads(json_match.group(1))
    else:
        # Fallback: parse manually
        score_data = {
            "match_score": 5,
            "matched_skills": [],
            "key_gaps": []
        }

    return score_data


if __name__ == "__main__":
    import sys
    
    # Test scoring a job (entry-level)
    test_job = {
        "title": "Associate Software Engineer",
        "company": "TechStartup",
        "location": "Remote",
        "description": "Looking for motivated junior developers to help build cloud-native applications. Responsibilities include writing clean Python code, working with databases, and collaborating with senior developers. Entry-level position perfect for someone with basic Python knowledge and interest in web development."
    }

    result = score_job(
        test_job["title"],
        test_job["company"],
        test_job["location"],
        test_job["description"]
    )
    print(json.dumps(result, indent=2))
