"""How form questions get answered. Edit freely.

Each rule is (pattern, answer). The pattern is a regular expression matched, ignoring case,
against the question's label. The FIRST rule that matches wins, so specific rules go first.

An answer can be:
  "text"            used as is. These placeholders are filled from resume.json:
                    {first} {last} {full} {legal_name} {email} {phone} {phone_national}
                    {city} {state} {location} {linkedin_url} {github_url} {gitlab_url} {availability} {work_authorization}
                    {gender} {race_ethnicity} {veteran_status} {disability_status} {nationality}
                    {sexual_orientation} {transgender}
  ["a", "b"]        for dropdowns and radio buttons: the first of these that matches an option
  "@DECLINE"        pick the "decline to answer / prefer not to say" option
  ""                leave the field blank (no question asked)

Questions that match no rule are looked up in learned_answers.json (answers you typed before),
and otherwise you are asked in the terminal and the answer is remembered.
Long free-text questions ("Why do you want to work here?") are drafted by the local model.
"""

ANSWER_RULES = [
    # ---- identity and contact
    (r"legal (first )?name", "{legal_name}"),
    (r"preferred (first )?name|nickname", "{first}"),
    (r"first name|given name", "{first}"),
    (r"last name|family name|surname", "{last}"),
    (r"full name|^name\b|your name", "{full}"),
    (r"e-?mail", "{email}"),
    (r"phone device type|device type", ["Mobile", "Cell"]),
    (r"country phone code|phone code", ["United States of America (+1)", "United States (+1)", "+1"]),
    (r"phone|mobile|\bcell\b", "{phone_national}"),
    (r"linkedin", "{linkedin_url}"),        # blank until you add a "linkedin" key to contact in resume.json
    (r"github", "{github_url}"),
    (r"gitlab", "{gitlab_url}"),
    (r"website|portfolio|personal site", "{github_url}"),
    (r"\bcity\b", "{city}"),
    (r"\bstate\b|province", "{state}"),
    (r"zip|postal", ""),
    (r"current location|where are you (located|based)|(?<!re)location", "{location}"),
    (r"country", ["United States", "United States of America", "USA", "US"]),

    # ---- work authorization (order matters: "without sponsorship" means Yes)
    (r"(authorized|eligible|legally|right) .*(work|employment).*(without|not (require|need)).*sponsor", ["Yes"]),
    (r"(require|need).*sponsor|sponsor.*(now or|future|visa|require)|\bvisa\b", ["No"]),
    (r"authorized to work|legally (authorized|permitted|able)|eligible to work|right to work", ["Yes"]),
    (r"18 years|over 18|at least 18", ["Yes"]),
    (r"work authorization|citizenship status", "{work_authorization}"),

    # ---- availability
    (r"start date|earliest.*start|when can you start|availab",
     ["Immediately", "Immediate", "ASAP", "As soon as possible", "{availability}"]),
    (r"notice period", ["None", "No notice", "Immediately", "0", "{availability}"]),

    # ---- how you found the job
    (r"how did you (hear|find)|where did you (hear|find)|referral source|source of (hire|application)", ["LinkedIn", "Job board", "Indeed", "Online", "Other"]),

    # ---- voluntary self-identification (EEO). Filled from the "self_identification" block of resume.json.
    # An empty value, or one that matches none of the form's options, falls back to the "decline" option.
    # Order matters: "transgender" must come before "gender".
    (r"transgender", ["{transgender}", "@DECLINE"]),
    (r"sexual orientation", ["{sexual_orientation}", "@DECLINE"]),
    (r"gender|\bsex\b", ["{gender}", "@DECLINE"]),
    (r"\brace\b|ethnic|hispanic|latino", ["{race_ethnicity}", "@DECLINE"]),
    (r"veteran", ["{veteran_status}", "@DECLINE"]),
    (r"disabilit", ["{disability_status}", "@DECLINE"]),
    (r"nationality", ["{nationality}", "@DECLINE"]),
    (r"pronoun", "@DECLINE"),
]

# Legal attestations are never filled for you: they are skipped and listed for you to handle.
NEVER_ANSWER = r"signature|certify|attest|under penalty"

from config.profile_loader import apply_overrides  # noqa: E402
apply_overrides(globals())