"""Decides what to put in each form field.

Order for every question:
  1. legal attestations (config/answers.py NEVER_ANSWER)  -> left for you
  2. rules in config/answers.py                            -> filled from resume.json
  3. answers you typed before (learned_answers.json)
  4. long free-text questions                              -> drafted by the local model (you review)
  5. anything else                                         -> you are asked in the terminal, and it is remembered
"""

import json
import re
from pathlib import Path

from config.answers import ANSWER_RULES, NEVER_ANSWER
from config.apply_settings import (
    ASK_ABOUT_UNKNOWN, DRAFT_FREE_TEXT, FREE_TEXT_MAX_WORDS, LEARNED_ANSWERS_FILE,
)
from config.settings import DESCRIPTION_CHARS_WRITING

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

CHOICE_KINDS = {"select", "radio", "combobox"}
DECLINE_RE = re.compile(
    r"decline|prefer not|do not wish|don.?t wish|not to (say|answer|disclose|identify|specify)|choose not|rather not",
    re.IGNORECASE,
)


# ------------------------------------------------------------------------ small helpers


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def pick_option(answer: str, options: list[str]) -> str | None:
    """The option that best matches `answer` ("Yes" matches "Yes, I am authorized"), or None."""
    a = _norm(answer)
    if not a:
        return None
    normed = [(o, _norm(o)) for o in options]
    for o, n in normed:
        if n == a:
            return o
    for o, n in normed:
        if n.startswith(a + " ") or a.startswith(n + " "):
            return o
    if len(a) >= 4:
        for o, n in normed:
            if re.search(rf"\b{re.escape(a)}\b", n):
                return o
    return None


def pick_decline(options: list[str]) -> str | None:
    return next((o for o in options if DECLINE_RE.search(o)), None)


def label_key(label: str) -> str:
    return _norm(label)


def resume_values(resume: dict) -> dict:
    """Placeholders available to the answers in config/answers.py."""
    contact = resume.get("contact", {})
    words = resume.get("name", "").split()
    digits = re.sub(r"\D", "", contact.get("phone", ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    phone_national = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}" if len(digits) == 10 else contact.get("phone", "")
    location = contact.get("location", "")
    parts = [part.strip() for part in location.split(",")]
    city, state = parts[0], (parts[1] if len(parts) > 1 else "")   # "Norfolk, VA, United States" -> VA

    def url(value: str, base: str) -> str:
        value = (value or "").strip()
        return value if not value or value.startswith("http") else f"{base}{value}"

    return {
        "first": words[0] if words else "",
        "last": words[-1] if words else "",
        "full": resume.get("name", ""),
        "legal_name": resume.get("legal_name") or resume.get("name", ""),
        "email": contact.get("email", ""),
        "phone": contact.get("phone", ""),
        "phone_national": phone_national,
        "location": location,
        "city": city,
        "state": state,
        "github_url": url(contact.get("github", ""), "https://github.com/"),
        "gitlab_url": url(contact.get("gitlab", ""), "https://gitlab.com/"),
        "availability": resume.get("availability", ""),
        "work_authorization": resume.get("work_authorization", ""),
    }


# ----------------------------------------------------------------------------- the answerer


class Answerer:
    """Answers form questions for one job. `ask` is input() by default (a stand-in in tests)."""

    def __init__(self, resume: dict, job: dict, ask=input, learned_file=LEARNED_ANSWERS_FILE,
                 ask_unknown: bool = ASK_ABOUT_UNKNOWN, draft_free_text: bool = DRAFT_FREE_TEXT,
                 drafter=None):
        self.resume = resume
        self.job = job
        self.values = resume_values(resume)
        self.ask = ask
        self.learned_file = Path(learned_file)
        self.ask_unknown = ask_unknown
        self.draft_free_text = draft_free_text
        self.drafter = drafter or self._draft_with_model
        try:
            self.learned = json.loads(self.learned_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.learned = {}

    # -- public

    def answer(self, field: dict) -> tuple[str | None, str]:
        """(value, source) for one field. value None = left for you; "" = deliberately blank.

        field: {"label", "kind", "options"}
        source: rule | learned | draft | asked | blank | never | unknown
        """
        label, kind, options = field["label"], field["kind"], field.get("options") or []
        if re.search(NEVER_ANSWER, label, re.IGNORECASE):
            return None, "never"

        for pattern, answer in ANSWER_RULES:
            if re.search(pattern, label, re.IGNORECASE):
                result = self._from_rule(answer, kind, options)
                if result is not None:
                    return result
                break  # the rule matched but its answer isn't one of this question's options

        key = label_key(label)
        if key in self.learned:
            value = self._fit(self.learned[key], kind, options)
            if value is not None:
                return value, "learned"

        if kind == "textarea" and self.draft_free_text:
            text = self.drafter(label)
            if text:
                return text, "draft"

        if self.ask_unknown:
            value = self._ask_user(label, kind, options)
            if value is not None:
                self._remember(key, value)
                return value, "asked"
        return None, "unknown"

    # -- rules

    def _from_rule(self, answer, kind: str, options: list[str]):
        if answer == "@DECLINE":
            if kind in CHOICE_KINDS:
                choice = pick_decline(options)
                return (choice, "rule") if choice else None
            return "", "blank"
        candidates = answer if isinstance(answer, list) else [answer]
        for candidate in candidates:
            try:
                text = candidate.format(**self.values)
            except (KeyError, IndexError, ValueError) as e:
                raise ValueError(
                    f"An answer in config/answers.py has a problem ({e!r}). "
                    f"Allowed placeholders: {', '.join('{' + k + '}' for k in self.values)}."
                ) from None
            if text == "":
                return "", "blank"
            fitted = self._fit(text, kind, options)
            if fitted is not None:
                return fitted, "rule"
        return None

    @staticmethod
    def _fit(text: str, kind: str, options: list[str]) -> str | None:
        """For choice fields the answer must be one of the options; text fields take it as is."""
        if kind in CHOICE_KINDS and options:
            return pick_option(text, options) or (
                pick_option(STATES[text.upper()], options) if text.upper() in STATES else None)
        return text

    # -- asking you

    def _ask_user(self, label: str, kind: str, options: list[str]) -> str | None:
        print(f"\n  ? No answer rule for: {label}")
        if kind in CHOICE_KINDS and options:
            for i, option in enumerate(options, 1):
                print(f"      {i}. {option}")
            reply = self.ask("    Number or text (Enter to skip): ").strip()
            if not reply:
                return None
            if reply.isdigit() and 1 <= int(reply) <= len(options):
                return options[int(reply) - 1]
            return pick_option(reply, options)
        reply = self.ask("    Your answer (Enter to skip): ").strip()
        return reply or None

    def _remember(self, key: str, value: str) -> None:
        self.learned[key] = value
        try:
            self.learned_file.write_text(json.dumps(self.learned, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            print(f"  (could not save the answer: {e})")

    # -- drafting

    def _draft_with_model(self, question: str) -> str | None:
        """Draft a short first-person answer from the resume and the posting. You review it."""
        from documents.application_maker import _ask, _resume_facts, clean_style  # heavy import, only needed here
        from config.writing_style import STYLE_RULES, TRUTH_RULES

        prompt = (
            f"Answer this job application question as {self.resume.get('name', 'the applicant')}.\n\n"
            f"QUESTION: {question}\n\n"
            f"JOB: {self.job.get('title', '')} at {self.job.get('company', '')}\n"
            f"{(self.job.get('description') or '')[:DESCRIPTION_CHARS_WRITING]}\n\n"
            f"RESUME FACTS (the only facts you may use):\n{_resume_facts(self.resume)}\n\n"
            f"{TRUTH_RULES}\n\n{STYLE_RULES}\n\n"
            f"Write {FREE_TEXT_MAX_WORDS} words or fewer, in first person, as plain prose. "
            "No greeting, no sign-off. If the resume gives no honest answer, say so in one short sentence "
            'instead of inventing one. Reply as JSON: {"answer": "..."}'
        )
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
        try:
            text = clean_style(str(_ask(prompt, schema).get("answer", "")).strip())
        except Exception as e:
            print(f"  (the model could not draft an answer: {e})")
            return None
        words = text.split()
        return " ".join(words[:FREE_TEXT_MAX_WORDS]) if words else None
