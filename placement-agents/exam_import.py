"""Import your exam timetable PDF.   python exam_import.py timetable.pdf
The PDF text is read locally (pypdf), an LLM turns it into a list, you review it, then it is saved.
Works with OpenRouter or Anthropic. Scanned/image-only PDFs have no text: use /exam instead."""
import json
import re
import sys
from datetime import date
import db
import llm
from agents import tracker

PROMPT = """Below is text from a college exam timetable. Extract every exam. Reply with ONLY a JSON array:
[{"subject": "...", "date": "YYYY-MM-DD", "time": "HH:MM or empty"}]
Dates may be DD-MM-YYYY or DD/MM/YYYY (day first). Today is %s. Skip holidays/non-exam rows.

TEXT:
%s"""


def extract(pdf_path: str) -> list[dict]:
    from pypdf import PdfReader
    text = "\n".join(p.extract_text() or "" for p in PdfReader(pdf_path).pages)
    if len(text.strip()) < 20:
        raise ValueError("no text in PDF (scanned image?)")
    out = llm.chat(PROMPT % (date.today().isoformat(), text[:12000]), max_tokens=2000)
    return json.loads(re.search(r"\[.*\]", out, re.S).group(0))


def main(path):
    if not llm.available():
        raise SystemExit("Set OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) in .env first")
    db.init()
    exams = extract(path)
    print("Found exams:")
    for e in exams:
        print(f"  {e['date']}  {e['subject']}  {e.get('time', '')}")
    if input("Save these? [y/N] ").strip().lower() != "y":
        return
    for e in exams:
        tracker.add_event("exam", e["subject"], e["date"], e["date"])
    print(f"Saved {len(exams)} exams.")


if __name__ == "__main__":
    main(sys.argv[1])
