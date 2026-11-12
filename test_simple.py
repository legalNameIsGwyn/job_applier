#!/usr/bin/env python3
"""
Simple Test for Job Scraper
Run: python test_simple.py
"""

import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*60)
print("JOB SCRAPER SIMPLE TEST")
print("="*60)

# Test 1: Imports
print("\n[TEST 1] Checking imports...")
try:
    from core import db, scraper, filters, scorer, job_info, job_status, tracking
    from config import settings, keywords, filter_rules, apply_settings
    from documents import application_maker
    print("[PASS] All imports successful")
except Exception as e:
    print(f"[FAIL] Import error: {e}")
    sys.exit(1)

# Test 2: Config
print("\n[TEST 2] Checking configuration...")
try:
    print(f"  OLLAMA_MODEL: {settings.OLLAMA_MODEL}")
    print(f"  DB_PATH: {settings.DB_PATH}")
    print(f"  SITES: {settings.SITES}")
    print(f"  SEARCH_TERMS: {settings.SEARCH_TERMS}")
    print(f"  REQUEST_TIMEOUT_SECONDS: {settings.REQUEST_TIMEOUT_SECONDS}")
    print("[PASS] Configuration OK")
except Exception as e:
    print(f"[FAIL] Config error: {e}")
    sys.exit(1)

# Test 3: Resume file
print("\n[TEST 3] Checking resume file...")
resume_path = os.path.join(os.path.dirname(settings.DB_PATH), "resume.json")
if os.path.exists(resume_path):
    print(f"[PASS] Resume found: {resume_path}")
else:
    print(f"[FAIL] Resume not found: {resume_path}")
    sys.exit(1)

# Test 4: Database
print("\n[TEST 4] Checking database...")
if os.path.exists(settings.DB_PATH):
    print(f"[PASS] Database exists: {settings.DB_PATH}")
else:
    print(f"[FAIL] Database not found: {settings.DB_PATH}")
    print("  Run: python main.py --init-db")

# Test 5: Model check
print("\n[TEST 5] Checking model...")
try:
    import subprocess
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        timeout=10
    )
    models = [m.strip().split()[0] for m in result.stdout.strip().split('\n') if m.strip()]
    if models:
        print(f"[PASS] Ollama running with models: {', '.join(models)}")
    else:
        print("[FAIL] No models found")
except FileNotFoundError:
    print("[FAIL] Ollama not installed")
except Exception as e:
    print(f"[FAIL] Model check failed: {e}")

print("\n" + "="*60)
print("TEST COMPLETE")
print("="*60)
print("\nNext steps:")
print("1. If model check failed, install the model: ollama pull qwen2.5:7b")
print("2. If database is empty, run: python main.py --init-db")
print("3. Run full test: python test_job_scraper.py")
