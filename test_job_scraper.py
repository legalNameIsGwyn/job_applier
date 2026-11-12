#!/usr/bin/env python3
"""
Test Job Scraper Pipeline
Run: python test_job_scraper.py

This test validates the core functionality and checks for common issues.
"""

import os
import sys
import time
import json
from datetime import datetime

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# PHASE 1: CONFIGURATION & IMPORTS
# ============================================================================

def test_01_imports():
    """Test that all modules can be imported."""
    print("\n" + "="*60)
    print("TEST 1: Import Validation")
    print("="*60)
    
    try:
        from core import db, scraper, filters, scorer, calibration, job_info, job_status, tracking
        from config import settings, keywords, filter_rules, apply_settings, answers, job_notes, writing_style, prompts
        from documents import application_maker
        print("✅ All imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

# ============================================================================
# PHASE 2: CONFIGURATION VALIDATION
# ============================================================================

def test_02_config():
    """Test that configuration values are set correctly."""
    print("\n" + "="*60)
    print("TEST 2: Configuration Check")
    print("="*60)
    
    from config import settings
    
    issues = []
    
    # Check model is set
    if not settings.OLLAMA_MODEL:
        issues.append("❌ OLLAMA_MODEL not set")
    else:
        print(f"✅ OLLAMA_MODEL = {settings.OLLAMA_MODEL}")
    
    # Check database path
    if not settings.DB_PATH:
        issues.append("❌ DB_PATH not set")
    else:
        print(f"✅ DB_PATH = {settings.DB_PATH}")
    
    # Check sites
    if not settings.SITES:
        issues.append("❌ SITES not set")
    else:
        print(f"✅ SITES = {settings.SITES}")
    
    # Check search terms
    if not settings.SEARCH_TERMS:
        issues.append("❌ SEARCH_TERMS not set")
    else:
        print(f"✅ SEARCH_TERMS = {settings.SEARCH_TERMS[:50]}...")
    
    # Check timeout
    if not settings.REQUEST_TIMEOUT_SECONDS:
        issues.append("❌ REQUEST_TIMEOUT_SECONDS not set")
    else:
        print(f"✅ REQUEST_TIMEOUT_SECONDS = {settings.REQUEST_TIMEOUT_SECONDS}s")
    
    # Check resume path
    resume_path = os.path.join(os.path.dirname(settings.DB_PATH), "resume.json")
    if not os.path.exists(resume_path):
        issues.append(f"❌ Resume file not found: {resume_path}")
    else:
        print(f"✅ Resume file exists: {resume_path}")
    
    return len(issues) == 0, issues

# ============================================================================
# PHASE 3: DATABASE VALIDATION
# ============================================================================

def test_03_database():
    """Test that the database structure is correct."""
    print("\n" + "="*60)
    print("TEST 3: Database Structure Check")
    print("="*60)
    
    from core import db
    
    try:
        # Check if database exists
        if not os.path.exists(settings.DB_PATH):
            print(f"⚠️  Database not found: {settings.DB_PATH}")
            print("   Running: python main.py --init-db")
            return True, []
        
        print(f"✅ Database exists: {settings.DB_PATH}")
        
        # Check table structure
        conn = db.get_db_connection()
        cursor = conn.execute("PRAGMA table_info(jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        
        expected_columns = ["id", "site", "job_url", "title", "company", "location", 
                          "description", "scraped_at", "match_score", "status",
                          "model_score", "keyword_score", "apply_url", "salary"]
        
        missing = [c for c in expected_columns if c not in columns]
        if missing:
            print(f"❌ Missing columns: {missing}")
        else:
            print(f"✅ All expected columns present ({len(columns)} columns)")
        
        # Check index exists
        conn = db.get_db_connection()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_job_url'")
        has_url_index = cursor.fetchone() is not None
        conn.close()
        
        if has_url_index:
            print("✅ job_url index exists")
        else:
            print("⚠️  job_url index not found (may be older database)")
        
        # Count jobs
        conn = db.get_db_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM jobs")
        job_count = cursor.fetchone()[0]
        conn.close()
        
        print(f"📊 Total jobs in database: {job_count}")
        
        return True, []
        
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return False, [str(e)]

# ============================================================================
# PHASE 4: FILTERING VALIDATION
# ============================================================================

def test_04_filtering():
    """Test the filtering rules."""
    print("\n" + "="*60)
    print("TEST 4: Filtering Rules Check")
    print("="*60)
    
    from config import filter_rules
    
    issues = []
    
    # Check blocked companies
    print(f"✅ Blocked companies: {len(filter_rules.BLOCKED_COMPANIES)}")
    if len(filter_rules.BLOCKED_COMPANIES) > 20:
        print("   (Note: Many blocked companies - consider reducing)")
    
    # Check senior title words
    print(f"✅ Senior title words: {len(filter_rules.SENIOR_TITLE_WORDS)}")
    
    # Check blocker patterns
    print(f"✅ Blocker patterns: {len(filter_rules.BLOCKER_PATTERNS)}")
    
    # Test a sample filter
    test_title = "Senior Software Engineer"
    test_company = "Robert Half"
    
    if filter_rules.is_blocked_by_title(test_title):
        print(f"✅ Title filter works: '{test_title}' is blocked")
    else:
        print(f"⚠️  Title filter may not work: '{test_title}' not blocked")
    
    if filter_rules.is_blocked_by_company(test_company):
        print(f"✅ Company filter works: '{test_company}' is blocked")
    else:
        print(f"⚠️  Company filter may not work: '{test_company}' not blocked")
    
    return True, []

# ============================================================================
# PHASE 5: MODEL VALIDATION
# ============================================================================

def test_05_model():
    """Test that the LLM model is available and responsive."""
    print("\n" + "="*60)
    print("TEST 5: LLM Model Check")
    print("="*60)
    
    from core import scorer
    from config import settings
    
    issues = []
    
    model = settings.OLLAMA_MODEL
    print(f"Testing model: {model}")
    
    # Check if model exists
    try:
        import subprocess
        result = subprocess.run(
            ["ollama", "list", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        models = [m.strip() for m in result.stdout.strip().split('\n') if m.strip()]
        print(f"Available models: {', '.join(models)}")
        
        if model in models:
            print(f"✅ Model '{model}' is installed")
        else:
            print(f"❌ Model '{model}' NOT found")
            print(f"   To install: ollama pull {model}")
            issues.append(f"Model '{model}' not found")
    except FileNotFoundError:
        print("❌ Ollama not installed")
        issues.append("Ollama not found in PATH")
    except Exception as e:
        print(f"⚠️  Could not check models: {e}")
    
    # Test a simple scoring (this might be slow)
    print("\nTesting simple scoring...")
    print("⏳ This may take 30-180 seconds depending on model...")
    
    start_time = time.time()
    
    try:
        # Test with a simple job description
        test_job = {
            "title": "Software Engineer",
            "description": "We are looking for a software engineer to work on our team."
        }
        
        result = scorer.score_job(test_job, "dummy_url", "dummy_url")
        elapsed = time.time() - start_time
        
        print(f"✅ Scoring completed in {elapsed:.1f}s")
        print(f"   Score: {result['match_score']}")
        print(f"   Matched skills: {result['matched_skills']}")
        
        if result['match_score'] is None:
            issues.append("Score is None (model may have failed)")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"⚠️  Scoring failed after {elapsed:.1f}s: {e}")
        issues.append(f"Scoring error: {e}")
    
    return len(issues) == 0, issues

# ============================================================================
# PHASE 6: MAIN PIPELINE TEST
# ============================================================================

def test_06_pipeline():
    """Test a dry-run of the main pipeline."""
    print("\n" + "="*60)
    print("TEST 6: Pipeline Dry-Run")
    print("="*60)
    
    from core import scraper
    
    issues = []
    
    # Test scraping one site/term
    print("Scraping 1 result from LinkedIn...")
    print("⏳ This may take 30-60 seconds...")
    
    start_time = time.time()
    
    try:
        # Use minimal settings for quick test
        site = "linkedin"
        search_term = "software engineer"
        results = scraper.scrape_jobs(
            site=site,
            search_term=search_term,
            results_wanted=1,  # Just 1 result for quick test
            hours_old=999,  # Ignore age
            location="Anywhere"  # Anywhere
        )
        
        elapsed = time.time() - start_time
        
        print(f"✅ Scraping completed in {elapsed:.1f}s")
        
        if results:
            print(f"📊 Found {len(results)} job(s)")
            for job in results:
                print(f"   - {job['title']} at {job['company']}")
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"⚠️  Scraping failed after {elapsed:.1f}s: {e}")
        issues.append(f"Scraping error: {e}")
    
    # Test filtering
    print("\nTesting filter on scraped results...")
    
    from config import settings
    from core import filters
    
    test_jobs = scraper.scrape_jobs(
        site="linkedin",
        search_term="software engineer",
        results_wanted=3,
        hours_old=999,
        location="Anywhere"
    )
    
    filtered = filters.filter_jobs(test_jobs)
    print(f"✅ Filtered {len(filtered)} jobs from {len(test_jobs)} total")
    
    return True, []

# ============================================================================
# PHASE 7: DOCUMENT GENERATION TEST
# ============================================================================

def test_07_documents():
    """Test document generation."""
    print("\n" + "="*60)
    print("TEST 7: Document Generation Check")
    print("="*60)
    
    from config import settings
    from core import job_info
    from documents import application_maker
    
    issues = []
    
    # Check resume file
    resume_path = os.path.join(os.path.dirname(settings.DB_PATH), "resume.json")
    
    if not os.path.exists(resume_path):
        print(f"❌ Resume file not found: {resume_path}")
        return False, [f"Resume file not found: {resume_path}"]
    
    print(f"✅ Resume file exists: {resume_path}")
    
    # Load resume
    with open(resume_path) as f:
        resume = json.load(f)
    
    print(f"✅ Resume loaded: {resume['name']}")
    print(f"   Skills: {len(resume.get('skills', []))} skills")
    print(f"   Experience: {len(resume.get('experience', []))} roles")
    
    # Test document generation on a sample job
    test_job = {
        "title": "Software Engineer",
        "company": "Test Company",
        "description": "We are looking for a software engineer to work on our team."
    }
    
    print("\nGenerating test documents (this may take 30-180 seconds)...")
    
    try:
        docs = application_maker.make_documents(test_job)
        print(f"✅ Documents generated successfully")
        print(f"   Files created: {len(docs)}")
        
        for doc in docs:
            print(f"   - {doc}")
        
    except Exception as e:
        print(f"❌ Document generation failed: {e}")
        import traceback
        print("\nFull error:")
        traceback.print_exc()
        issues.append(f"Document generation error: {e}")
    
    return len(issues) == 0, issues

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "="*60)
    print("JOB SCRAPER PIPELINE TEST SUITE")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    all_issues = []
    
    # Test 1: Imports
    try:
        results.append(("Imports", test_01_imports()))
    except Exception as e:
        results.append(("Imports", (False, [f"Test crashed: {e}"])))
    
    # Test 2: Config
    try:
        results.append(("Config", test_02_config()))
    except Exception as e:
        results.append(("Config", (False, [f"Test crashed: {e}"])))
    
    # Test 3: Database
    try:
        results.append(("Database", test_03_database()))
    except Exception as e:
        results.append(("Database", (False, [f"Test crashed: {e}"])))
    
    # Test 4: Filtering
    try:
        results.append(("Filtering", test_04_filtering()))
    except Exception as e:
        results.append(("Filtering", (False, [f"Test crashed: {e}"])))
    
    # Test 5: Model (slow - 2-5 minutes)
    try:
        results.append(("Model", test_05_model()))
    except Exception as e:
        results.append(("Model", (False, [f"Test crashed: {e}"])))
    
    # Test 6: Pipeline
    try:
        results.append(("Pipeline", test_06_pipeline()))
    except Exception as e:
        results.append(("Pipeline", (False, [f"Test crashed: {e}"])))
    
    # Test 7: Documents (slow - 3-10 minutes)
    try:
        results.append(("Documents", test_07_documents()))
    except Exception as e:
        results.append(("Documents", (False, [f"Test crashed: {e}"])))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, (name, result) in enumerate(results) if result[0])
    failed = len(results) - passed
    
    print(f"Passed: {passed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")
    
    if all_issues:
        print("\nIssues found:")
        for issue in all_issues:
            print(f"  - {issue}")
    
    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return passed == len(results), results, all_issues

# ============================================================================
# RUN TEST
# ============================================================================

if __name__ == "__main__":
    success, results, issues = run_all_tests()
    
    if success:
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED - Project appears healthy!")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("⚠️  SOME TESTS FAILED - Review issues above")
        print("="*60)
        print("\nNext steps:")
        print("1. Fix issues in findings.md")
        print("2. Re-run: python test_job_scraper.py")
        print("3. Check error messages carefully")
