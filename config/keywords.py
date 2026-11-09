"""Keyword matching: how postings' wording maps to the skills on your resume.

Used to move the posting's own skills to the front of your resume, to pick relevant
projects, to compute the keyword score, and to report what the posting wants that you
don't have. Nothing here is ever added to your resume.
"""

# Your resume skill  ->  other ways a posting might write it.
# The skill's own name always matches too. Matching is whole-word and case-insensitive.
SKILL_ALIASES = {
    "Spring Boot": ["springboot", "spring boot"],
    "JavaScript": ["javascript", "js", "ecmascript"],
    "Node.js": ["node.js", "nodejs"],
    "Express.js": ["express.js", "expressjs"],
    "REST API Development": ["rest api", "rest apis", "restful api", "restful apis", "restful", "rest services"],
    "MySQL": ["mysql", "sql"],
    "Bash scripting": ["bash", "shell scripting", "shell"],
    "Linux": ["linux", "unix"],
    "Git": ["git", "github", "gitlab", "version control"],
    "Manual Testing": ["manual testing", "manual tests", "test cases", "testing"],
    "Automated Testing": ["automated testing", "test automation", "automated tests", "automation testing"],
    "Quality Assurance": ["quality assurance", "qa"],
    "Production Support": ["production support", "application support", "operations support"],
    "LLMs/AI": ["llm", "llms", "large language model", "large language models", "generative ai", "genai", "ai"],
    "RAG": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "Microsoft Office": ["microsoft office", "ms office", "office 365", "m365"],
    "Eloquent ORM": ["eloquent"],
    "HTML5": ["html5", "html"],
    "CSS": ["css", "css3"],
    "VLANs": ["vlan", "vlans"],
    "Network Design": ["network design", "networking"],
    "Cisco Packet Tracer": ["packet tracer"],
}

# Common terms postings ask for. Reported (never added) when a posting uses one
# and your resume has no matching skill.
COMMON_TERMS = [
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "React", "Angular", "Vue", "TypeScript", "C++", ".NET",
    "Go", "Rust", "Ruby", "Django", "Flask", "FastAPI", "PostgreSQL", "MongoDB", "Redis", "SQL Server",
    "Oracle", "CI/CD", "Jenkins", "Terraform", "GraphQL", "Selenium", "Agile", "Scrum", "Kotlin", "Swift",
    "Tableau", "Power BI", "Splunk", "ServiceNow",
]

CASE_SENSITIVE_TERMS = ["Go", "Swift"]