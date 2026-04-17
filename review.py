"""
Rewrite My Website: page reviewer logic.
Importable module. Use review_page(url) -> dict.
"""
import os
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import anthropic

# Load .env if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        val = v.strip().strip('"').strip("'")
        if val and not os.environ.get(k.strip()):
            os.environ[k.strip()] = val

RUBRIC = """You are reviewing a page from an animal shelter or rescue's website. Apply this rubric.

TONE & VOICE
- Warm, welcoming, human, not clinical or bureaucratic
- Never guilt-trip, shame, or lecture (especially surrenderers, finders, or people asking questions)
- Thank the reader for visiting, caring, or helping, where natural and not performative
- Assume good intent from every visitor

CLARITY & CONCISION
- Cut word count aggressively; every sentence earns its place
- Remove repetition and redundancy
- Short paragraphs, short sentences, plain language (~8th grade reading level)
- Replace jargon ("intake," "disposition") with human terms
- NEVER use em dashes (—) in the rewrite. Use periods, commas, colons, or parentheses instead.

COMPLETENESS
- Flag pages that are too thin. Every page should answer: What is this? Who is it for? What do I do next? What happens after?
- If key info is missing, note it in the rewrite as [NEEDS: ___]

STRUCTURE & FLOW
- Lead with welcome and the ask, not the rules. Requirements and red tape go lower on the page.
- Reframe rules as help: "Here's what you'll need" instead of "You must provide…"
- Every page has a clear primary ask or next step (one CTA)
- Use bullets/numbers for instructions, never bury them in prose

REDUCE RED TAPE
- Flag excessive requirements, gatekeeping, or multi-step hoops
- If a process has more than ~5 steps, call it out
- Replace "we reserve the right to deny" energy with "here's how we work together"

INCLUSIVITY & ACCESS
- No assumptions about housing, income, family structure, work schedule, or experience
- Avoid language that screens out renters, apartment dwellers, first-time adopters
- "Guardian" / "adopter" / "family" over "owner" where natural

LANGUAGE TO FIX
- Guilt/shame ("abandoned," "dumped," "gave up on") → neutral alternatives
- Gatekeeping ("We reserve the right to…") → "Here's what helps…"
- Clinical ("euthanasia," "intake," "disposition") → humane alternatives
- Cold closers → warm thank-you or invitation

CRITICAL: DO NOT REWRITE
- Sections tied to laws, ordinances, or required legal disclosures (bite holds, rabies quarantine, licensing, stray holds)
- Official policies (adoption contracts, surrender agreements, return policies)
- Medical/veterinary protocols
- When in doubt, preserve verbatim and flag in recommendations

PRESERVE
- Facts: hours, addresses, phone, fees, specific numbers
- Names of programs, staff, partners
- Required legal/policy text

OUTPUT FORMAT
Return ONLY valid JSON with this exact structure:
{
  "current_title": "the page's current title/H1",
  "suggested_title": "a better, warmer, clearer title",
  "rewrite_markdown": "the full rewritten page in markdown. Mark preserved legal/policy sections with a blockquote beginning with '> ⚖️ PRESERVED (see recommendations):' followed by the original text verbatim.",
  "recommendations": [
    {"type": "missing_info", "note": "..."},
    {"type": "structure", "note": "..."},
    {"type": "policy_section", "note": "..."},
    {"type": "tool_or_link", "note": "..."},
    {"type": "red_tape", "note": "..."},
    {"type": "other", "note": "..."}
  ],
  "page_type": "adoption | surrender | lost_found | foster | volunteer | donate | about | contact | other",
  "summary": "1-2 sentence overall assessment"
}
"""


def fetch_page(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (RewriteMyWebsite/1.0)"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Pull links BEFORE stripping nav/footer (shelters often have broken links in those)
    links = _extract_links(soup, base_url=url)

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    title = (soup.title.string if soup.title else "").strip()
    return title, text, links


def _extract_links(soup, base_url: str) -> list[tuple[str, str]]:
    """Return a deduped list of (href, link_text) for external-looking hrefs."""
    from urllib.parse import urljoin, urlparse
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
            continue
        # Resolve relative URLs
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        # Dedupe by URL (ignore fragments)
        key = full.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        link_text = a.get_text(" ", strip=True)[:80] or "(no text)"
        out.append((key, link_text))
    return out


def check_links(links: list[tuple[str, str]], max_workers: int = 10, timeout: int = 8) -> list[dict]:
    """Check each link with HEAD (fallback GET). Returns list of {url, text, status, note}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    headers = {"User-Agent": "Mozilla/5.0 (RewriteMyWebsite/1.0 LinkChecker)"}

    def check(url: str, text: str):
        try:
            r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
            # Some servers return 403/405 for HEAD; retry with GET
            if r.status_code in (403, 405, 501) or r.status_code >= 500:
                r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
                r.close()
            return {"url": url, "text": text, "status": r.status_code, "note": ""}
        except requests.exceptions.Timeout:
            return {"url": url, "text": text, "status": 0, "note": "timeout"}
        except requests.exceptions.ConnectionError as e:
            return {"url": url, "text": text, "status": 0, "note": "connection error"}
        except Exception as e:
            return {"url": url, "text": text, "status": 0, "note": type(e).__name__}

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(check, u, t) for u, t in links]
        for fut in as_completed(futures):
            results.append(fut.result())
    # Sort broken first, then by status
    def priority(r):
        s = r["status"]
        if s == 0 or s >= 400:
            return (0, s)
        return (1, s)
    results.sort(key=priority)
    return results


def review_page(url: str, check_links_flag: bool = False) -> dict:
    title, text, links = fetch_page(url)
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=RUBRIC,
        messages=[{
            "role": "user",
            "content": f"Page title: {title}\nURL: {url}\n\nPage content:\n---\n{text}\n---\n\nReview and return the JSON as specified."
        }]
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    data["_original_text"] = text
    data["_url"] = url
    if check_links_flag and links:
        data["_link_results"] = check_links(links)
    else:
        data["_link_results"] = None
    return data


def markdown_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    in_ul = in_ol = in_bq = False
    for line in lines:
        s = line.rstrip()
        if s.startswith("> "):
            if not in_bq:
                out.append("<blockquote>"); in_bq = True
            out.append(s[2:] + "<br>")
            continue
        elif in_bq:
            out.append("</blockquote>"); in_bq = False
        if re.match(r"^\s*[-*]\s+", s):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append("<li>" + re.sub(r"^\s*[-*]\s+", "", s) + "</li>")
            continue
        elif in_ul:
            out.append("</ul>"); in_ul = False
        if re.match(r"^\s*\d+\.\s+", s):
            if not in_ol:
                out.append("<ol>"); in_ol = True
            out.append("<li>" + re.sub(r"^\s*\d+\.\s+", "", s) + "</li>")
            continue
        elif in_ol:
            out.append("</ol>"); in_ol = False
        if s.startswith("### "):
            out.append(f"<h4>{s[4:]}</h4>")
        elif s.startswith("## "):
            out.append(f"<h3>{s[3:]}</h3>")
        elif s.startswith("# "):
            out.append(f"<h2>{s[2:]}</h2>")
        elif s.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{s}</p>")
    if in_ul: out.append("</ul>")
    if in_ol: out.append("</ol>")
    if in_bq: out.append("</blockquote>")
    html = "\n".join(out)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    return html
