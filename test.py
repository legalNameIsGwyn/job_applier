from jobspy import scrape_jobs

jobs = scrape_jobs(
    site_name=["linkedin"],  # also , "linkedin", "zip_recruiter", "glassdoor" "bayt", "naukri", "bdjobs", "hellowork"
    search_term="desk",
    location="Norfolk, VA",
    results_wanted=100,
    hours_old=72,
    country_indeed="USA",
    # fetch_description=True,  # read each job's page on boards whose search results have no description (slower)
    # proxies=["user:pass@host:port", "localhost"],
)
print(f"Found {len(jobs)} jobs")
print(jobs.head())
jobs.to_csv("jobs.csv", index=False)