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

PAGE_TYPE_GUIDANCE = {
    "adoption": """
ADOPTION PAGE SPECIFIC GUIDANCE
- Lead with the animals, not with the rules. The first thing visitors should see is the invitation to meet pets, not the application requirements.
- Frame requirements as "what helps your application" rather than "what we require."
- Avoid language that screens out renters, apartment dwellers, first-time adopters, and lower-income households unless legally required.
- Consider open or conversation-based adoption practices over rigid checklists. Suggest moving to these if the page reads as gatekeeping.
- The fee should appear early but not first; never bury it.
- Add a clear, warm CTA: "Meet our pets," "Apply to adopt [Pet Name]," or similar.
""",
    "surrender": """
SURRENDER PAGE SPECIFIC GUIDANCE
- This is the hardest page on most shelter websites because the visitor is in distress. Use the warmest possible tone.
- Never use shaming language: no "abandonment," "giving up," "dumping," "irresponsible." These words drive people away or to worse outcomes.
- Frame the page as "We're here to help you find the right path for your pet." Many surrenders can be diverted with the right resources.
- Lead with rehoming alternatives (Adopt-a-Pet Rehome, Home To Home, Get Your Pet) before describing shelter intake. Most pets do better staying out of the shelter system.
- Be honest about wait times, fees, and outcomes without being clinical.
- Include behavioral, financial, and medical resources that may prevent surrender (food banks, low-cost vet care, training help).
""",
    "lost_found": """
LOST & FOUND PAGE SPECIFIC GUIDANCE
- Speed and clarity matter most. People on this page are panicked.
- Lead with the action: "Lost a pet? Start here." Numbered, scannable steps.
- Strongly recommend integrating Petco Love Lost (free facial recognition) and Pawboost.
- Make the shelter's lost pet hotline number prominent.
- Separate "I lost a pet" and "I found a pet" flows clearly. Don't combine them.
- Cover: stray hold periods, where to file a report, where to look (kennel hours), microchip lookup options.
""",
    "foster": """
FOSTER PAGE SPECIFIC GUIDANCE
- Emphasize the variety of fostering: short-term, medical, behavioral, kittens, seniors, "sleepovers." Many people don't realize foster comes in flexible commitments.
- Lead with "we provide everything" (food, supplies, vet care). Cost is the #1 barrier.
- Make the application low-friction. If it's long, suggest shortening or splitting into stages.
- Be specific about time commitment per foster type.
- Include a clear invitation: "Foster for a weekend," "Foster a kitten litter," etc.
""",
    "volunteer": """
VOLUNTEER PAGE SPECIFIC GUIDANCE
- Emphasize the variety of ways to help, especially non-direct-animal options (admin, fundraising, transport, photography, social media).
- Be clear about minimum age, time commitment, and training requirements without making them sound like barriers.
- Recommend SignUpGenius, Better Impact, or Volunteer Local for shift management if not already in use.
- Include a youth/family pathway if possible. Families want to volunteer together.
""",
    "donate": """
DONATE PAGE SPECIFIC GUIDANCE
- Lead with impact, not the donate button. "$25 covers a vaccine. $100 covers a spay surgery. $500 sponsors a pet's full care."
- Show multiple ways to give: one-time, monthly, in-kind (Amazon wishlist), planned giving, vehicle donation.
- Make the actual donation form fast. Recommend Donorbox, GiveButter, or Bloomerang if the current form is clunky.
- Include 501(c)(3) status and EIN for tax-deductibility transparency.
- Recurring/monthly donor options should be visually equal to one-time.
""",
    "about": """
ABOUT PAGE SPECIFIC GUIDANCE
- Make the mission concrete. Replace "to promote animal welfare" with specifics: how many animals, what services, what outcomes.
- Include real numbers if available (live release rate, animals served per year, years in operation).
- Introduce the team with warmth, not just titles.
- Include links to specific service pages so visitors can take action.
""",
    "contact": """
CONTACT PAGE SPECIFIC GUIDANCE
- Hours, phone, address, email should be the first things visible. Don't bury them.
- Include holiday hours and any temporary closures.
- Provide separate contacts for: adoption, lost & found, surrender, media, donations.
- Include a map or directions link.
""",
    "other": "",
}


TOOL_CATALOG = {
    "adoption": [
        {"name": "Petfinder", "url": "https://www.petfinder.com/", "what": "Free adoptable-pet listings widget"},
        {"name": "Adopt-a-Pet", "url": "https://www.adoptapet.com/", "what": "Free adoptable-pet listings"},
        {"name": "Best Friends Network", "url": "https://network.bestfriends.org/", "what": "Free network membership and resources"},
    ],
    "surrender": [
        {"name": "Adopt-a-Pet Rehome", "url": "https://rehome.adoptapet.com/", "what": "Free peer-to-peer rehoming platform; keeps pets out of shelters"},
        {"name": "Home To Home", "url": "https://home-home.org/", "what": "Free pet rehoming network; widget for shelter sites"},
        {"name": "Get Your Pet", "url": "https://www.getyourpet.com/", "what": "Direct adoption network; alternative to surrender"},
    ],
    "lost_found": [
        {"name": "Petco Love Lost", "url": "https://lost.petcolove.org/", "what": "Free facial recognition for lost pets; can embed on shelter sites"},
        {"name": "Pawboost", "url": "https://www.pawboost.com/", "what": "Free lost pet alerts to local network"},
        {"name": "Pet FBI", "url": "https://petfbi.org/", "what": "Free lost & found pet database"},
        {"name": "Finding Rover", "url": "https://findingrover.com/", "what": "Facial recognition pet finding platform"},
    ],
    "foster": [
        {"name": "Doobert", "url": "https://www.doobert.com/", "what": "Foster, transport, and volunteer coordination platform"},
        {"name": "JotForm foster app templates", "url": "https://www.jotform.com/form-templates/foster-application-form", "what": "Free customizable foster application forms"},
    ],
    "volunteer": [
        {"name": "SignUpGenius", "url": "https://www.signupgenius.com/", "what": "Free volunteer shift signups"},
        {"name": "Better Impact", "url": "https://www.betterimpact.com/", "what": "Volunteer management platform"},
        {"name": "Volunteer Local", "url": "https://www.volunteerlocal.com/", "what": "Volunteer scheduling and management"},
    ],
    "donate": [
        {"name": "Donorbox", "url": "https://donorbox.org/", "what": "Easy embedded donation forms with monthly options"},
        {"name": "GiveButter", "url": "https://givebutter.com/", "what": "Free fundraising platform with peer-to-peer features"},
        {"name": "Bloomerang", "url": "https://bloomerang.co/", "what": "Donor management and recurring giving"},
        {"name": "Amazon Wishlist", "url": "https://www.amazon.com/wishlist/", "what": "Free in-kind donation collection"},
    ],
    "about": [],
    "contact": [],
    "other": [],
}


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
- NEVER invent facts, services, hours, phone numbers, addresses, or programs that are not in the source text. If a page is mostly navigation/widgets with little real copy, say so clearly in the summary and keep the rewrite limited to what is actually on the page.
- If there is essentially no content to rewrite (page is empty, a widget shell, or just a navigation stub), do NOT fabricate one. The rewrite_markdown should explicitly state that the page has little or no content to rewrite, and the recommendations should focus on what the shelter needs to add.

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

    # Pull links BEFORE stripping anything (shelters often have broken links in nav/footer)
    links = _extract_links(soup, base_url=url)

    # Strip only script/style/noscript first (always safe to remove)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = (soup.title.string if soup.title else "").strip()

    # Try narrower containers first
    candidates = [
        soup.find("main"),
        soup.find(attrs={"role": "main"}),
        soup.find("article"),
        soup.find(id=re.compile(r"(content|main)", re.I)),
        soup.find(class_=re.compile(r"(content|main)", re.I)),
    ]
    best = None
    best_len = 0
    for c in candidates:
        if not c:
            continue
        t = c.get_text(" ", strip=True)
        if len(t) > best_len:
            best = c
            best_len = len(t)

    MIN_CONTENT_CHARS = 300
    if best and best_len >= MIN_CONTENT_CHARS:
        # Strip nav/footer/header from inside the chosen container
        container = best
        for tag in container(["nav", "footer", "header"]):
            tag.decompose()
        text = container.get_text("\n", strip=True)
    else:
        # Main container was empty or too thin. Use full body, keep nav/header/footer
        # because on thin sites those contain the actual visible content.
        source = soup.body or soup
        text = source.get_text("\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
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


def crawl_site_context(source_url: str, max_pages: int = 8, timeout: int = 10) -> list[dict]:
    """
    Fetch the site's homepage and a handful of internal pages to build a context map.
    Returns a list of {url, title, excerpt} dicts.
    Only fetches pages on the same host as source_url. Skips the source page itself.
    """
    from urllib.parse import urljoin, urlparse
    from concurrent.futures import ThreadPoolExecutor, as_completed

    parsed = urlparse(source_url)
    host = parsed.netloc.lower()
    if not host:
        return []
    root = f"{parsed.scheme}://{parsed.netloc}/"

    headers = {"User-Agent": "Mozilla/5.0 (RewriteMyWebsite/1.0 SiteContext)"}

    # Step 1: fetch the homepage (and the source page if different) to discover links
    candidates = set()
    seeds = {root, source_url}
    for seed in seeds:
        try:
            r = requests.get(seed, headers=headers, timeout=timeout)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
                    continue
                full = urljoin(seed, href).split("#", 1)[0]
                p = urlparse(full)
                if p.scheme not in ("http", "https"):
                    continue
                if p.netloc.lower() != host:
                    continue
                # Skip files
                if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|webp|mp4|mp3|zip|docx?|xlsx?)(\?|$)", full, re.I):
                    continue
                # Skip the source page
                if full.rstrip("/") == source_url.rstrip("/"):
                    continue
                candidates.add(full)
        except Exception:
            continue

    # Score candidates: prefer shorter paths (top-level pages) and those with shelter-relevant keywords
    keywords = ("adopt", "surrender", "rehome", "foster", "volunteer", "donate",
                "lost", "found", "contact", "about", "service", "program", "help",
                "spay", "neuter", "license", "event", "shelter", "rescue")

    def score(u: str) -> int:
        path = urlparse(u).path.lower()
        depth = path.strip("/").count("/")
        kw_hits = sum(1 for k in keywords if k in path)
        # Lower is better; depth penalized, keyword matches help
        return depth * 10 - kw_hits * 5

    ranked = sorted(candidates, key=score)[:max_pages]

    # Step 2: fetch each in parallel and extract title + excerpt
    def fetch_one(u: str):
        try:
            r = requests.get(u, headers=headers, timeout=timeout)
            if r.status_code >= 400:
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = (soup.title.string if soup.title else "").strip()
            h1 = soup.find("h1")
            if h1:
                h1_text = h1.get_text(" ", strip=True)
                if h1_text and len(h1_text) > len(title or ""):
                    title = h1_text
            body = soup.body or soup
            text = body.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            excerpt = text[:300]
            return {"url": u, "title": title or u, "excerpt": excerpt}
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(ranked) or 1)) as ex:
        futures = [ex.submit(fetch_one, u) for u in ranked]
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
    # Sort by score so output order is stable and meaningful
    results.sort(key=lambda r: score(r["url"]))
    return results


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


def _build_page_guidance_block() -> str:
    parts = ["\n\nPAGE-TYPE-SPECIFIC GUIDANCE\nApply the section that matches the page's type. Pick the page type that best fits the actual content.\n"]
    for ptype, guidance in PAGE_TYPE_GUIDANCE.items():
        if guidance.strip():
            parts.append(guidance)
    return "\n".join(parts)


def _build_tool_catalog_block() -> str:
    parts = ["\n\nFREE OR LOW-COST TOOLS YOU CAN RECOMMEND\nWhen relevant to the page type, suggest these as 'tool_or_link' recommendations. Only recommend tools that genuinely fit the page; do not stuff every tool into every report. When you recommend a tool, briefly say WHY it fits this specific page.\n"]
    for ptype, tools in TOOL_CATALOG.items():
        if not tools:
            continue
        parts.append(f"\nFor {ptype} pages:")
        for t in tools:
            parts.append(f"- {t['name']} ({t['url']}): {t['what']}")
    return "\n".join(parts)


def review_page(url: str, check_links_flag: bool = False, use_site_context: bool = False) -> dict:
    title, text, links = fetch_page(url)
    client = anthropic.Anthropic()
    page_guidance = _build_page_guidance_block()
    tool_catalog = _build_tool_catalog_block()

    site_context = ""
    site_map = []
    if use_site_context:
        site_map = crawl_site_context(url)
        if site_map:
            lines = []
            for p in site_map:
                lines.append(f"- {p['url']}\n  Title: {p['title']}\n  Excerpt: {p['excerpt']}")
            site_context = (
                "\n\nOTHER PAGES ON THIS SITE (for context only — do NOT rewrite these):\n"
                + "\n".join(lines)
                + "\n\nUse this site map when making recommendations. Suggest linking to existing pages "
                "instead of duplicating content. Flag information that contradicts or duplicates other pages. "
                "Suggest pages that should be added if they appear to be missing."
            )
    full_system = RUBRIC + page_guidance + tool_catalog
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=full_system,
        messages=[{
            "role": "user",
            "content": f"Page title: {title}\nURL: {url}\n\nPage content:\n---\n{text}\n---{site_context}\n\nReview and return the JSON as specified."
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
    data["_site_map"] = site_map if use_site_context else None
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
