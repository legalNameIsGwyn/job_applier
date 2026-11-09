import unittest
from scraper import scrape_jobs
from scorer import score_jobs
from filter_rules import filter_jobs
from resume_tailer import tailer_resumes
from apply_jobs import apply_jobs
from summary import generate_summary

class TestPipeline(unittest.TestCase):
    def test_pipeline(self):
        # Step 1: Scrape Jobs
        jobs = scrape_jobs(['https://example.com/jobs'])
        self.assertTrue(len(jobs) > 0)

        # Step 2: Score Jobs
        scores = score_jobs(jobs, 'resume.json')
        self.assertTrue(all(isinstance(score, float) for score in scores))

        # Step 3: Filter Jobs
        filtered_jobs = filter_jobs(jobs, scores)
        self.assertTrue(len(filtered_jobs) > 0)

        # Step 4: Tailor Resumes
        tailored_jobs = tailer_resumes(filtered_jobs, 'resume.json')
        self.assertTrue(len(tailored_jobs) > 0)

        # Step 5: Apply Jobs
        apply_jobs(tailored_jobs)

        # Step 6: Generate Summary
        summary = generate_summary(tailored_jobs, 'resume.json')
        self.assertTrue('new_jobs' in summary)
        self.assertTrue('failed_jobs' in summary)
        self.assertTrue('ready_for_application' in summary)

if __name__ == '__main__':
    unittest.main()
