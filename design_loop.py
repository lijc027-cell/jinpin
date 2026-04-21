#!/usr/bin/env python3
"""
Generator + Evaluator design loop.
Generator and evaluator are completely independent API calls with no shared context.
Both use DESIGN-apple.md as the standard.
Runs until evaluator finds no gaps or max rounds reached.
"""
from __future__ import annotations

import json
import os
import re
import sys

import anthropic

DESIGN_STANDARD_PATH = "/Users/l/Downloads/projects/前端风格文件集/DESIGN-apple.md"
WEBAPP_PATH = "/Users/l/Downloads/projects/竞品/src/jingyantai/webapp.py"
MAX_ROUNDS = 6

DESIGN_STANDARD = open(DESIGN_STANDARD_PATH, encoding="utf-8").read()

# ── Generator ──────────────────────────────────────────────────────────────────
GENERATOR_SYSTEM = """You are a frontend HTML/CSS/JS generator. Your ONLY job is to produce a complete, self-contained HTML page that faithfully implements the Apple design system standard provided to you.

STRICT RULES:
- Output ONLY the raw HTML (starting with <!doctype html> and ending with </html>). No markdown, no code fences, no explanation.
- All CSS must be in a <style> block inside <head>. All JS must be in a <script> block before </body>.
- The page is the 竞研台 (competitive intelligence) web app. Preserve all existing functionality.
- Apply EVERY gap point listed. Be precise with exact CSS values from the standard.
- Never use gradients, textures, or extra accent colors beyond Apple Blue (#0071e3).
- Body text must be left-aligned. Only headlines center-align.
- Pill CTAs use border-radius: 980px. Standard buttons use border-radius: 8px.
- Nav: 48px height, rgba(0,0,0,0.8) + backdrop-filter: saturate(180%) blur(20px).
- Alternate sections: #000000 (dark) and #f5f5f7 (light).
- SF Pro Display for 20px+, SF Pro Text below 20px.
- Apply negative letter-spacing at ALL text sizes."""

GENERATOR_USER_TMPL = """DESIGN STANDARD:
{standard}

CURRENT HTML:
{html}

GAPS TO FIX IN THIS ROUND:
{gaps}

Produce the complete improved HTML now. Output raw HTML only."""

# ── Evaluator ──────────────────────────────────────────────────────────────────
EVALUATOR_SYSTEM = """You are an independent frontend design evaluator. You have NO knowledge of who generated the HTML or how.

Your ONLY job: compare the provided HTML against the Apple design standard and identify specific, actionable gaps.

Output a JSON array. Each item:
  {"category": "...", "issue": "...", "fix": "..."}

Categories: Typography | Color | Layout | Spacing | Components | Navigation | Buttons | Cards | Responsive

Be precise — reference exact CSS values, pixel sizes, color codes from the standard.
If there are NO gaps, output exactly: []

Output ONLY the JSON array. No explanation, no markdown."""

EVALUATOR_USER_TMPL = """DESIGN STANDARD:
{standard}

HTML TO EVALUATE:
{html}

List all gaps as a JSON array."""


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY", "")
    base = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs: dict = {"api_key": key}
    if base:
        kwargs["base_url"] = base
    return anthropic.Anthropic(**kwargs)


def extract_html(text: str) -> str:
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    # Find doctype start
    lower = text.lower()
    start = lower.find("<!doctype")
    if start == -1:
        start = lower.find("<html")
    if start != -1:
        end = text.rfind("</html>")
        if end != -1:
            return text[start : end + len("</html>")]
    return text


def get_current_html(path: str) -> str:
    content = open(path, encoding="utf-8").read()
    match = re.search(r'INDEX_HTML = """(.*?)"""', content, re.DOTALL)
    if match:
        return match.group(1)
    raise ValueError("Could not find INDEX_HTML in webapp.py")


def update_webapp_html(path: str, new_html: str) -> None:
    content = open(path, encoding="utf-8").read()
    # Escape backslashes so Python triple-quoted string is valid
    escaped = new_html.replace("\\", "\\\\")
    # Ensure no triple-quote in HTML breaks the string
    escaped = escaped.replace('"""', '""\\"')
    new_content = re.sub(
        r'INDEX_HTML = """.*?"""',
        f'INDEX_HTML = """{escaped}"""',
        content,
        flags=re.DOTALL,
    )
    open(path, "w", encoding="utf-8").write(new_content)


def run_generator(client: anthropic.Anthropic, current_html: str, gaps: list[dict]) -> str:
    if gaps:
        gap_text = "\n".join(
            f"- [{g.get('category','?')}] {g.get('issue','?')} → Fix: {g.get('fix','?')}"
            for g in gaps
        )
    else:
        gap_text = "(First round — implement the full design standard from scratch)"

    user_msg = GENERATOR_USER_TMPL.format(
        standard=DESIGN_STANDARD,
        html=current_html,
        gaps=gap_text,
    )

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=GENERATOR_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        text = stream.get_final_message().content[0].text

    return extract_html(text)


def run_evaluator(client: anthropic.Anthropic, html: str) -> list[dict]:
    user_msg = EVALUATOR_USER_TMPL.format(standard=DESIGN_STANDARD, html=html)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=EVALUATOR_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = response.content[0].text.strip()

    # Extract JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        print(f"  [Evaluator] Warning: could not parse JSON, raw: {text[:200]}")
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        print(f"  [Evaluator] JSON parse error: {e}")
        return []


def main() -> None:
    print("=" * 70)
    print("Design Loop: Generator + Evaluator")
    print(f"Standard: {DESIGN_STANDARD_PATH}")
    print(f"Target:   {WEBAPP_PATH}")
    print("=" * 70)

    client = make_client()
    current_html = get_current_html(WEBAPP_PATH)
    gaps: list[dict] = []

    for round_num in range(1, MAX_ROUNDS + 1):
        print(f"\n{'─'*60}")
        print(f"  ROUND {round_num}")
        print(f"{'─'*60}")

        print(f"  [Generator] Generating improved HTML...")
        new_html = run_generator(client, current_html, gaps)
        print(f"  [Generator] Done — {len(new_html):,} chars")

        print(f"  [Evaluator] Evaluating against design standard...")
        gaps = run_evaluator(client, new_html)
        print(f"  [Evaluator] Found {len(gaps)} gap(s):")
        for g in gaps:
            print(f"    • [{g.get('category','?')}] {g.get('issue','?')}")

        current_html = new_html

        if not gaps:
            print(f"\n  ✓ No gaps — design matches standard.")
            break
        elif round_num < MAX_ROUNDS:
            print(f"\n  → Continuing to round {round_num + 1}...")
        else:
            print(f"\n  ⚠ Max rounds reached. Saving best result.")

    print(f"\n{'='*70}")
    print("  [Saving] Updating webapp.py INDEX_HTML...")
    update_webapp_html(WEBAPP_PATH, current_html)
    print("  [Done] webapp.py updated successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
