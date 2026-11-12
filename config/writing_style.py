"""How the cover letter should read, and which AI-sounding phrasing to catch.

STYLE_RULES goes into the prompt. SLOP_PATTERNS are regular expressions (raw strings,
case-insensitive) checked against the letter and summary afterwards: a match triggers
one rewrite attempt, and anything left is flagged in notes.txt.
"""

STYLE_RULES = """Style rules (follow all of them):
- Name the concrete thing: the tool, system or project, not a feeling about it. Prefer "I built an overtime tracker in Laravel" over "I am passionate about impactful solutions".
- Short, plain sentences in the active voice. Ordinary words ("use", not "leverage"; "help", not "foster").
- No em dashes, no colons in sentences, no bold, no emojis, no bullet points.
- No "not just X, but Y" sentences. No lists of three just for rhythm. Do not repeat a point in different words.
- Do not tack on "-ing" phrases that claim significance (", highlighting my ...", ", showcasing my ...").
- Do not use: delve, leverage, tapestry, testament, pivotal, crucial, vibrant, showcase, underscore, foster, realm, landscape, robust, seamless, cutting-edge, passionate, synergy, spearhead, myriad.
- No flattery of the company and no generic closing line. End on a specific, short invitation to talk.
- No hedging ("I believe", "I feel that")."""

# What each of the three letter paragraphs should do.
LETTER_STRUCTURE = """- Exactly 3 short paragraphs, 200 words or fewer in total.
- Paragraph 1: interest in this specific role and company, and the most relevant thing from the resume.
- Paragraph 2: two or three concrete examples from the real experience or projects that match what the job asks for.
- Paragraph 3: a brief, confident close that invites a conversation."""

LETTER_WARN_WORDS = 280  # warn in notes.txt if the letter is longer than this

SLOP_PATTERNS = {
    "AI vocabulary": r"\b(delv\w+|leverag\w+|tapestry|testament|pivotal|crucial|vibrant|showcas\w+|underscor\w+|"
                     r"foster\w*|realm|landscape|robust|seamless\w*|cutting-edge|passionate|synerg\w+|"
                     r"spearhead\w*|myriad|multifaceted|dynamic)\b",
    "'not just X, but Y'": r"\bnot (?:just|only|merely)\b[^.]{0,80}\bbut\b",
    "'-ing' significance tail": r",\s+(?:highlighting|showcasing|underscoring|demonstrating|reflecting|ensuring|enabling)\b",
    "chatbot phrasing": r"\b(i hope this (?:letter |message |email )?finds you|i am writing to|i would be (?:thrilled|delighted)|"
                        r"great question)\b",
    "filler": r"\b(in order to|due to the fact that|it is important to note|at the end of the day|in today's)\b",
    "hedging": r"\b(i believe|i feel that)\b",
}


# ------------------------------------------------------------------------- the prompts
# Prompts are Python format strings. {placeholders} are filled in by the code; a literal
# brace must be doubled ({{ and }}), as in the JSON example at the bottom of LETTER_PROMPT.
# Keep the "Return JSON" lines: the code needs the model to answer with exactly those keys.

# Added to both prompts. Keeps the model from inventing anything.
TRUTH_RULES = (
    "Use ONLY facts stated in the resume data. Never invent employers, job titles, dates, "
    "numbers, metrics, tools, certifications or degrees. If the job asks for something that is "
    "not in the resume, do not claim it. A role with an end date is finished, so write about it "
    "in the past tense."
)

# Placeholders: {resume_facts} {job_title} {company} {description} {truth_rules}
#               {max_skills} {max_projects}
TAILOR_PROMPT = """You are helping tailor an entry-level software resume to one job.

RESUME DATA:
{resume_facts}

JOB: {job_title} at {company}
{description}

{truth_rules}
{years_rule}
Return JSON with:
- "summary": 2 plain sentences, under 60 words, rewriting the resume summary to fit this job. Keep the degree and the real roles; do not add new claims. Where it is true, use the posting's own wording for my skills. No em dashes and no buzzwords (leverage, passionate, dynamic, robust).
- "relevant_skills": up to {max_skills} skills copied EXACTLY from the resume skills list, most relevant to this job first.
- "project_names": up to {max_projects} project names copied EXACTLY from the resume, most relevant first."""

# Placeholders: {name} {resume_facts} {job_title} {company} {job_location} {description}
#               {truth_rules} {letter_structure} {keyword_rule} {authorization_rule} {style_rules}
LETTER_PROMPT = """Write the BODY of a cover letter for this job, in first person, as {name}.

RESUME DATA:
{resume_facts}

JOB: {job_title} at {company} ({job_location})
{description}

{truth_rules}

Requirements:
{letter_structure}
- Use the exact job title "{job_title}" and the company name "{company}" once each.
{keyword_rule}{years_rule}{authorization_rule}- Do NOT include a greeting ("Dear ..."), a sign-off, the name, a date or any placeholder in brackets.

{style_rules}

Return JSON: {{"paragraphs": ["...", "...", "..."]}}"""

# Added only when the posting asks for more years of experience than you have.
# {asked} = years the posting asks for, {have} = your years. The letter must not mention the numbers.
LETTER_YEARS_RULE = (
    "- The posting asks for {asked}+ years of experience and I have about {have}. Do not state either number "
    "and do not apologize for it. Show I am ready with facts from the resume instead: the skills that match, "
    "a real project or job task that used them, and how quickly I picked them up. Include one short sentence "
    "about my willingness to learn, tied to something specific in the resume (a skill learned on the job, a "
    "training, a certification).\n"
)
SUMMARY_YEARS_RULE = (
    "This job asks for more years of experience than I have. In the summary, lead with the skills that match "
    "and the real projects, keep the willingness to learn from my original summary, and do not mention years.\n"
)

# Optional lines in the letter prompt. Each line is left out when it doesn't apply.
# {keywords} = skills of yours that the posting mentions (left out if there are none)
LETTER_KEYWORD_RULE = (
    "- Where it is true, use the posting's own wording for these skills I actually have: {keywords}. "
    "Use each at most once, inside a real example, never as a list.\n"
)
# {work_authorization} and {availability_clause} come from resume.json (left out if it has neither)
LETTER_AUTHORIZATION_RULE = (
    "- In paragraph 3, say in one short sentence that I am a {work_authorization}{availability_clause}.\n"
)
LETTER_AVAILABILITY_CLAUSE = " and available for an {availability}"  # {availability} from resume.json
