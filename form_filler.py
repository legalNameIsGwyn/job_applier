"""Fills a job application form in a Playwright page. It never clicks Submit.

Works on ordinary HTML forms (Greenhouse, Lever and Ashby all use them): it scans every field,
works out each field's question from its label, asks answering.Answerer for an answer, and
fills it. Fields it can't answer are left empty and reported so you can finish them by hand.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from answering import Answerer, pick_option

SCAN_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && r.right > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const optionLabel = c => {
    if (c.id) { const l = document.querySelector('label[for="' + CSS.escape(c.id) + '"]'); if (l) return txt(l); }
    const w = c.closest('label'); if (w) return txt(w);
    const sib = c.nextElementSibling || c.nextSibling; if (sib && txt(sib)) return txt(sib);
    return txt(c.parentElement) || c.value || '';
  };
  const ownLabel = c => {
    const al = c.getAttribute('aria-label'); if (al) return al;
    const ids = c.getAttribute('aria-labelledby');
    if (ids) { const t = ids.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean).map(txt).join(' '); if (t) return t; }
    if (c.id) { const l = document.querySelector('label[for="' + CSS.escape(c.id) + '"]'); if (l) return txt(l); }
    const w = c.closest('label'); if (w) return txt(w);
    return '';
  };
  const groupLabel = members => {
    const first = members[0];
    const fs = first.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg && txt(lg)) return txt(lg); }
    let p = first.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      const inner = [...p.querySelectorAll('input, select, textarea')].filter(x => x.type !== 'hidden');
      if (inner.some(x => !members.includes(x))) break;
      const cands = [...p.querySelectorAll('legend, label, [class*="label" i], [class*="question" i]')]
        .filter(l => !members.some(m => l.contains(m) || (m.id && l.getAttribute('for') === m.id)));
      const hit = cands.find(l => txt(l));
      if (hit) return txt(hit);
    }
    return '';
  };

  document.querySelectorAll('[data-aj]').forEach(e => e.removeAttribute('data-aj'));  // ids from an earlier scan
  const out = [], radios = {};
  let n = 0;
  for (const c of document.querySelectorAll('input, select, textarea, button[aria-haspopup="listbox"]')) {
    const isList = c.tagName === 'BUTTON';
    const t = isList ? 'listbox' : (c.type || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'password'].includes(t)) continue;
    if (c.disabled || c.getAttribute('aria-hidden') === 'true') continue;
    const boxy = t === 'radio' || t === 'checkbox';
    // Radios, checkboxes and file inputs are often styled invisible with a visible label or wrapper,
    // so for those the parent counts. Anything inside a hidden section (an earlier wizard page) is skipped.
    const shown = vis(c) || (c.parentElement && vis(c.parentElement));
    if (!shown && (boxy || t === 'file')) continue;
    if (t !== 'file' && !boxy && (!vis(c) || c.tabIndex === -1)) continue;   // skips honeypot fields
    c.setAttribute('data-aj', String(n));
    const id = String(n++);
    const raw = ownLabel(c) || groupLabel([c]) || c.getAttribute('placeholder') || c.name || '';
    const required = c.required || c.getAttribute('aria-required') === 'true' || /[*✱]/.test(raw);
    const label = raw.replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim();

    if (isList) {
      const shown = txt(c);
      out.push({ id, kind: 'combobox', label, required, options: [], value: /^(select|choose)/i.test(shown) ? '' : shown });
      continue;
    }
    if (t === 'radio') {
      const key = c.name || ('r' + id);
      (radios[key] = radios[key] || []).push(c);
      continue;
    }
    if (t === 'checkbox') { out.push({ id, kind: 'checkbox', label, required, options: [], value: c.checked ? 'on' : '' }); continue; }
    if (t === 'file') { out.push({ id, kind: 'file', label: label + ' ' + (c.name || '') + ' ' + (c.id || ''), required, options: [], value: '' }); continue; }
    if (c.tagName === 'SELECT') {
      const options = [...c.options].filter(o => !o.disabled && o.value !== '' && !/^(select|choose|please select|--)/i.test(o.text.trim())).map(o => o.text.trim());
      const cur = c.selectedIndex >= 0 && c.value !== '' ? c.options[c.selectedIndex].text.trim() : '';
      out.push({ id, kind: 'select', label, required, options, value: cur });
      continue;
    }
    const combo = c.getAttribute('role') === 'combobox' || c.getAttribute('aria-haspopup') === 'listbox';
    out.push({ id, kind: c.tagName === 'TEXTAREA' ? 'textarea' : (combo ? 'combobox' : 'text'),
               label, required, options: [], value: c.value || '' });
  }
  for (const key in radios) {
    const members = radios[key];
    const raw = groupLabel(members) || members[0].getAttribute('aria-label') || key;
    out.push({ id: members[0].getAttribute('data-aj'), kind: 'radio',
      label: raw.replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim(),
      required: members.some(m => m.required) || /[*✱]/.test(raw),
      options: members.map(m => optionLabel(m)), option_ids: members.map(m => m.getAttribute('data-aj')),
      value: members.some(m => m.checked) ? 'on' : '' });
  }
  return out;
}
"""

OPTIONS = '[role="option"], [role="listbox"] li'

FORM_FIELDS = "input[type=file], textarea, input[type=text], input[type=email], input[type=tel]"


@dataclass
class Report:
    filled: list = field(default_factory=list)       # (label, shown value, source)
    attention: list = field(default_factory=list)    # (label, why)
    uploaded: list = field(default_factory=list)     # file names


def find_form_frame(page):
    """The frame (the page itself, or an embedded iframe) with the most form fields."""
    best, best_n = None, 0
    for frame in page.frames:
        try:
            n = frame.locator(FORM_FIELDS).count()
        except Exception:
            continue
        if n > best_n:
            best, best_n = frame, n
    return best if best_n >= 3 else None


def open_application(page, url: str, timeout_ms: int = 30000):
    """Go to the application page and return the frame holding the form (or None)."""
    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    for attempt in range(2):
        for _ in range(12):  # up to ~6 s for a script-built form to appear
            frame = find_form_frame(page)
            if frame:
                return frame
            page.wait_for_timeout(500)
        if attempt == 0:  # a job description page: click its Apply button and look again
            button = page.locator('a:has-text("Apply"), button:has-text("Apply")').filter(visible=True).first
            try:
                button.click(timeout=3000)
            except Exception:
                break
            page.wait_for_load_state("domcontentloaded")
    return None


def _letter_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    try:
        from docx import Document
        return "\n\n".join(p.text for p in Document(str(path)).paragraphs if p.text.strip())
    except Exception:
        return ""


def fill_form(frame, answerer: Answerer, resume_file: Path | None, letter_file: Path | None) -> Report:
    """Fill every field we can. Returns what was filled and what needs you."""
    report = Report()
    resume_done = False
    letter_text = _letter_text(letter_file)
    fields = frame.evaluate(SCAN_JS)

    def loc(field_id: str):
        return frame.locator(f'[data-aj="{field_id}"]')

    for f in fields:
        label, kind = f["label"] or "(unlabeled field)", f["kind"]
        try:
            if kind == "file":
                lowered = f["label"].lower()
                is_letter = "cover" in lowered
                path = letter_file if is_letter else resume_file
                if path and path.exists() and (is_letter or not resume_done or re.search(r"resume|cv", lowered)):
                    loc(f["id"]).set_input_files(str(path))
                    report.uploaded.append(path.name)
                    resume_done = resume_done or not is_letter
                elif f["required"]:
                    report.attention.append((label.strip(), "needs a file upload"))
                continue

            if kind == "checkbox":
                if f["required"]:
                    report.attention.append((label, "required checkbox, left for you"))
                continue

            if f["value"]:  # already filled in (pre-filled by the site, or by an earlier run)
                continue

            if kind == "textarea" and re.search(r"cover letter", label, re.IGNORECASE) and letter_text:
                loc(f["id"]).fill(letter_text)
                report.filled.append((label, "(your cover letter)", "file"))
                continue

            options = f["options"]
            if kind == "combobox":
                options = _open_combobox_options(frame, loc(f["id"]))
            value, source = answerer.answer({"label": label, "kind": kind, "options": options})

            if kind == "combobox" and (value is None or value == ""):
                _close_dropdown(frame)  # we opened it to read the choices; leave it closed
            if value is None:
                if f["required"] or source == "never":
                    why = "left for you (legal statement)" if source == "never" else "required, no answer"
                    report.attention.append((label, why))
                continue
            if value == "":
                continue

            if kind in ("text", "textarea"):
                loc(f["id"]).fill(value)
            elif kind == "select":
                loc(f["id"]).select_option(label=value)
            elif kind == "radio":
                index = f["options"].index(value)
                target = loc(f["option_ids"][index])
                try:
                    target.check(force=True, timeout=2000)
                except Exception:
                    target.locator("xpath=ancestor::label[1]").click(timeout=2000)
            elif kind == "combobox":
                _choose_combobox(frame, loc(f["id"]), value)

            shown = value if len(value) <= 60 else value[:57] + "..."
            report.filled.append((label, shown, source))
            if source == "draft":
                report.attention.append((label, "drafted by the model: read it before sending"))
        except Exception as e:  # one bad field must not stop the rest
            detail = " ".join(str(e).split())[:90]
            report.attention.append((label, f"could not fill it ({type(e).__name__}: {detail})"))
    return report


def _open_combobox_options(frame, box) -> list[str]:
    """Open a dropdown widget and read its choices (empty if it loads them as you type)."""
    try:
        box.click(timeout=2000)
        frame.wait_for_timeout(300)
        return [t.strip() for t in frame.locator(OPTIONS).filter(visible=True).all_inner_texts() if t.strip()]
    except Exception:
        return []


def _close_dropdown(frame) -> None:
    try:
        (frame.page if hasattr(frame, "page") else frame).keyboard.press("Escape")
    except Exception:
        pass


def _choose_combobox(frame, box, value: str) -> None:
    """Pick `value` from a dropdown widget, typing to filter if the list loads on typing."""
    if not frame.locator(OPTIONS).filter(visible=True).count():  # not already open from reading its options
        box.click(timeout=2000)
    texts = [t.strip() for t in frame.locator(OPTIONS).filter(visible=True).all_inner_texts()]
    if not texts:
        try:
            box.fill(value)  # a type-to-search box (not available on button dropdowns)
        except Exception:
            pass
        frame.wait_for_timeout(500)
        texts = [t.strip() for t in frame.locator(OPTIONS).filter(visible=True).all_inner_texts()]
    chosen = pick_option(value, texts) or (texts[0] if texts else None)
    if not chosen:
        raise ValueError("no options appeared")
    frame.locator(OPTIONS).filter(has_text=chosen).filter(visible=True).first.click(timeout=2000)
