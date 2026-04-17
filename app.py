"""
Rewrite My Website: Flask web app.
Run locally: python3 app.py
Deploy on Render: gunicorn app:app
"""
import os
import re
import csv
import json
import uuid
import time
import base64
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from io import BytesIO

from flask import Flask, request, render_template_string, redirect, url_for, abort
import requests

from review import review_page, markdown_to_html

app = Flask(__name__)

# --- Paths ---
ROOT = Path(__file__).parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
EMAILS_CSV = DATA / "emails.csv"
IP_LOG = DATA / "ip_usage.json"
DATA.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)
if not EMAILS_CSV.exists():
    EMAILS_CSV.write_text("timestamp,email,url,report_id,ip\n")

# --- Config ---
DAILY_LIMIT = 5
BASE_URL = os.environ.get("BASE_URL", "")  # set in Render to public URL
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "Rewrite My Website <onboarding@resend.dev>")

# ==================== TEMPLATES ====================

PAGE_CSS = """
:root {
  --teal: #2d8a8a; --teal-dark: #1f5f5f; --teal-light: #e0efec;
  --sage: #3b7a57; --sage-light: #eaf3ee;
  --blue: #4a7fa7; --blue-light: #e6eef5;
  --warm: #c97b5a; --warm-light: #f5e9e2;
  --bg: #f4f9f8; --text: #1f3a3a; --muted: #5a7575;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  margin: 0; background: var(--bg); color: var(--text); line-height: 1.6; }
.container { max-width: 820px; margin: 0 auto; padding: 40px 20px; }
header { text-align: center; padding: 50px 20px 30px; }
h1 { color: var(--teal-dark); font-size: 2.4em; margin: 0; }
.tagline { color: var(--sage); font-style: italic; font-size: 1.1em; margin-top: 6px; }
h2 { color: var(--teal-dark); margin-top: 40px; }
a { color: var(--teal); }
.card { background: #fff; border: 1px solid #c9dedc; border-radius: 8px;
  padding: 28px; margin: 20px 0; box-shadow: 0 2px 6px rgba(45,138,138,0.08); }
form label { display: block; font-weight: 600; color: var(--teal-dark); margin: 14px 0 6px; }
form input[type=email], form input[type=url] { width: 100%; padding: 10px 12px; font-size: 16px;
  border: 1px solid #b9d6c4; border-radius: 6px; background: #fff; }
form input:focus { outline: none; border-color: var(--teal); box-shadow: 0 0 0 3px rgba(45,138,138,0.15); }
button, .btn { background: var(--teal); color: white; border: none; padding: 12px 24px;
  border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: 600; display: inline-block; text-decoration: none; }
button:hover, .btn:hover { background: var(--teal-dark); }
button:disabled { background: #9bbfbd; cursor: not-allowed; }
.fineprint { color: var(--muted); font-size: 14px; margin-top: 16px; }
.notice { background: var(--sage-light); border-left: 4px solid var(--sage); padding: 14px 18px;
  border-radius: 4px; margin: 20px 0; }
.error { background: var(--warm-light); border-left: 4px solid var(--warm); padding: 14px 18px;
  border-radius: 4px; margin: 20px 0; }
footer { text-align: center; color: var(--muted); font-size: 14px; padding: 40px 20px; }
ul.features li { margin: 8px 0; }
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rewrite My Website | A Tool for Animal Shelters and Rescues</title>
<style>{{ css|safe }}</style>
</head><body>
<header>
  <h1>Rewrite My Website</h1>
  <div class="tagline">A Tool for Animal Shelters and Rescues</div>
</header>

<div class="container">
  <div class="card">
    <p>Your website is often the first impression of your organization. Many animal shelter and rescue
    websites are outdated, too long, or are simply not very welcoming. This tool fixes all of that.</p>
    <p>Simply paste a URL from your website below. We'll send you back a friendlier, clearer rewrite,
    plus recommendations to help the page work harder for the animals in your care.</p>
  </div>

  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if notice %}<div class="notice">{{ notice }}</div>{% endif %}

  <div class="card">
    <form method="POST" action="/review" id="reviewForm">
      <label for="email">Your email</label>
      <input type="email" id="email" name="email" required placeholder="you@rescue.org">

      <label for="url">Page URL to review</label>
      <input type="url" id="url" name="url" required placeholder="https://yourshelter.org/adopt">

      <label style="display:flex; align-items:center; gap:8px; font-weight:400; margin-top:18px; cursor:pointer;">
        <input type="checkbox" id="check_links" name="check_links" value="1" style="width:18px; height:18px; margin:0;">
        <span>Also check this page for broken links (adds about 10 to 30 seconds)</span>
      </label>

      <div style="margin-top: 20px;">
        <button type="submit" id="submitBtn">Review this page</button>
      </div>
      <div id="loadingMsg" style="display:none; margin-top:18px; padding:14px 18px; background:var(--teal-light); border-left:4px solid var(--teal); border-radius:4px; color:var(--teal-dark);">
        <strong>Reviewing your page...</strong> This takes about 30 to 60 seconds. Please don't close this tab.
      </div>
    </form>
    <script>
      document.getElementById('reviewForm').addEventListener('submit', function() {
        var btn = document.getElementById('submitBtn');
        btn.disabled = true;
        btn.innerText = 'Working on it...';
        document.getElementById('loadingMsg').style.display = 'block';
      });
    </script>
  </div>

</div>

<footer>
  Created by Kristen Hassen of <a href="https://www.outcomesforpets.com" target="_blank" rel="noopener">Outcomes for Pets</a>.
</footer>
</body></html>
"""

REPORT_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rewrite My Website | {{ current_title }}</title>
<style>{{ css|safe }}
  .meta { color: var(--muted); font-size: 14px; margin-bottom: 20px; }
  .summary { background: var(--teal-light); border-left: 4px solid var(--teal); padding: 16px 20px; margin: 20px 0; border-radius: 4px; }
  .titles { background: var(--sage-light); border: 1px solid #b9d6c4; padding: 14px 18px; border-radius: 4px; margin: 20px 0; }
  .titles strong { color: var(--sage); }
  .rewrite { background: #fff; border: 1px solid #c9dedc; padding: 24px; border-radius: 6px; margin: 20px 0; box-shadow: 0 1px 3px rgba(45,138,138,0.06); }
  .rewrite blockquote { background: var(--blue-light); border-left: 4px solid var(--blue); padding: 12px 16px; margin: 16px 0; border-radius: 4px; color: #2c4a66; }
  .rec { background: #fff; border-left: 4px solid var(--blue); padding: 10px 14px; margin: 8px 0; border-radius: 4px; box-shadow: 0 1px 2px rgba(45,138,138,0.05); }
  .rec-type { display: inline-block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; background: var(--blue); color: white; padding: 2px 8px; border-radius: 10px; margin-right: 8px; font-weight: 600; }
  .rec-type.red_tape { background: var(--warm); }
  .rec-type.missing_info { background: #d49a5a; }
  .rec-type.policy_section { background: #6b8aa8; }
  .rec-type.tool_or_link { background: #5a9e7a; }
  .rec-type.structure { background: var(--teal); }
  .original { display: none; background: #f0f6f5; border: 1px dashed #9bbfbd; padding: 16px; margin-top: 12px; border-radius: 4px; white-space: pre-wrap; font-size: 14px; color: #3a5555; }
  .original.shown { display: block; }
  .action-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 24px; }
  .action-row button { background: var(--teal); color: white; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-size: 15px; font-weight: 600; }
  .action-row button:hover { background: var(--teal-dark); }
  .action-row button:disabled { background: #9bbfbd; cursor: not-allowed; }
  .status-banner { padding: 12px 16px; border-radius: 4px; margin: 14px 0; font-weight: 500; }
  .status-banner.success { background: var(--sage-light); border-left: 4px solid var(--sage); color: var(--sage); }
  .status-banner.error { background: var(--warm-light); border-left: 4px solid var(--warm); color: #8a4a2e; }
  .link-row { display: flex; gap: 12px; padding: 10px 12px; margin: 6px 0; background: #fff; border-left: 4px solid var(--warm); border-radius: 4px; }
  .link-status { flex-shrink: 0; min-width: 70px; font-weight: 700; color: var(--warm); font-size: 14px; padding-top: 2px; }
  .link-info { flex: 1; min-width: 0; }
  .link-text { font-weight: 500; color: var(--text); margin-bottom: 2px; }
  .link-info a { word-break: break-all; font-size: 14px; color: var(--muted); }
</style></head><body>

<header>
  <h1 style="font-size:2em;">Rewrite My Website</h1>
  <div class="tagline">A Tool for Animal Shelters and Rescues</div>
</header>

<div class="container">
  <div class="meta">Page reviewed: <a href="{{ url }}">{{ url }}</a></div>

  <div class="summary"><strong>Summary:</strong> {{ summary }}</div>

  <div class="titles">
    <div><strong>Current title:</strong> {{ current_title }}</div>
    <div><strong>Suggested title:</strong> {{ suggested_title }}</div>
    <div style="margin-top:6px; font-size:13px; color:var(--muted);">Page type: {{ page_type }}</div>
  </div>

  <h2>Suggested Rewrite</h2>
  <div class="rewrite" id="rewriteBlock">{{ rewrite_html|safe }}</div>

  {% if status_msg %}
  <div class="status-banner {{ status_kind }}">{{ status_msg }}</div>
  {% endif %}

  <div class="action-row">
    <button type="button" id="copyRewriteBtn" onclick="copyText('rewrite')">Copy rewrite</button>
    <button type="button" id="copyFullBtn" onclick="copyText('full')">Copy rewrite + recommendations</button>
    <form method="POST" action="/email-pdf/{{ report_id }}" style="display:inline;">
      <button type="submit" id="emailBtn">Email me a PDF{% if email %} ({{ email }}){% endif %}</button>
    </form>
  </div>

  <h2>Recommendations</h2>
  <div class="recs" id="recsBlock">
    {% for r in recommendations %}
    <div class="rec"><span class="rec-type {{ r.type }}">{{ r.type.replace('_',' ') }}</span>{{ r.note }}</div>
    {% else %}
    <p>No recommendations.</p>
    {% endfor %}
  </div>

  {% if link_results is not none %}
  <h2>Broken Links</h2>
  {% set broken = link_results | selectattr('status', 'ge', 400) | list + link_results | selectattr('status', 'eq', 0) | list %}
  {% if broken %}
  <div style="margin-bottom:12px; color:var(--warm);"><strong>{{ broken|length }} link(s) need attention out of {{ link_results|length }} checked.</strong></div>
  <div class="links" id="linksBlock">
    {% for r in link_results %}
      {% if r.status == 0 or r.status >= 400 %}
      <div class="link-row broken">
        <div class="link-status">{% if r.status == 0 %}{{ r.note or 'failed' }}{% else %}{{ r.status }}{% endif %}</div>
        <div class="link-info">
          <div class="link-text">{{ r.text }}</div>
          <a href="{{ r.url }}" target="_blank" rel="noopener">{{ r.url }}</a>
        </div>
      </div>
      {% endif %}
    {% endfor %}
  </div>
  {% else %}
  <p style="color:var(--sage);">All {{ link_results|length }} links checked are working.</p>
  {% endif %}
  {% endif %}

  <h2>Original Text</h2>
  <button onclick="document.getElementById('orig').classList.toggle('shown')">Show / Hide Original</button>
  <div class="original" id="orig">{{ original_text }}</div>

  <div style="margin-top:40px;"><a href="/" class="btn">Back to start</a></div>
</div>

<script>
  function copyText(mode) {
    var rewrite = document.getElementById('rewriteBlock').innerText || '';
    var text = rewrite;
    if (mode === 'full') {
      var recs = document.getElementById('recsBlock').innerText || '';
      text = 'SUGGESTED REWRITE\n\n' + rewrite + '\n\n\nRECOMMENDATIONS\n\n' + recs;
    }
    var btnId = mode === 'full' ? 'copyFullBtn' : 'copyRewriteBtn';
    var btn = document.getElementById(btnId);
    navigator.clipboard.writeText(text).then(function() {
      var original = btn.innerText;
      btn.innerText = 'Copied!';
      btn.disabled = true;
      setTimeout(function() { btn.innerText = original; btn.disabled = false; }, 2000);
    }, function() {
      alert('Copy failed. You can select the text manually.');
    });
  }
  var emailForm = document.querySelector('form[action^="/email-pdf/"]');
  if (emailForm) {
    emailForm.addEventListener('submit', function() {
      var btn = document.getElementById('emailBtn');
      btn.disabled = true;
      btn.innerText = 'Sending...';
    });
  }
</script>

<footer>
  Created by Kristen Hassen of <a href="https://www.outcomesforpets.com" target="_blank" rel="noopener">Outcomes for Pets</a>.
</footer>
</body></html>
"""

# ==================== HELPERS ====================

def load_ip_log():
    if not IP_LOG.exists():
        return {}
    try:
        return json.loads(IP_LOG.read_text())
    except Exception:
        return {}

def save_ip_log(data):
    IP_LOG.write_text(json.dumps(data))

def check_rate_limit(ip: str) -> tuple[bool, int]:
    """Returns (allowed, remaining)."""
    log = load_ip_log()
    today = datetime.now(timezone.utc).date().isoformat()
    entry = log.get(ip, {})
    if entry.get("date") != today:
        entry = {"date": today, "count": 0}
    allowed = entry["count"] < DAILY_LIMIT
    remaining = max(0, DAILY_LIMIT - entry["count"])
    return allowed, remaining

def record_usage(ip: str):
    log = load_ip_log()
    today = datetime.now(timezone.utc).date().isoformat()
    entry = log.get(ip, {"date": today, "count": 0})
    if entry.get("date") != today:
        entry = {"date": today, "count": 0}
    entry["count"] += 1
    log[ip] = entry
    # prune old entries (>7 days)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    log = {k: v for k, v in log.items() if v.get("date", "0") >= cutoff}
    save_ip_log(log)

def save_email(email, url, report_id, ip):
    with EMAILS_CSV.open("a", newline="") as f:
        w = csv.writer(f)
        w.writerow([datetime.now(timezone.utc).isoformat(), email, url, report_id, ip])

def _mc(pdf, h, text):
    """multi_cell that always returns the cursor to the left margin on the next line."""
    pdf.multi_cell(w=0, h=h, text=text, new_x="LMARGIN", new_y="NEXT")


def generate_pdf_bytes(data: dict) -> bytes:
    """Render report data to a PDF using fpdf2 (pure Python, no system deps)."""
    from fpdf import FPDF

    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(left=54, top=54, right=54)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(31, 95, 95)
    pdf.cell(0, 26, "Rewrite My Website", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(59, 122, 87)
    pdf.cell(0, 16, "A Tool for Animal Shelters and Rescues", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # Meta line
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 117, 117)
    _mc(pdf,12, _latin1_safe(f"Page reviewed: {data.get('_url','')}"))
    pdf.ln(6)

    # Summary
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(31, 95, 95)
    pdf.cell(0, 14, "Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(31, 58, 58)
    _mc(pdf,15, _latin1_safe(data.get("summary", "")))
    pdf.ln(6)

    # Titles
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(59, 122, 87)
    pdf.cell(0, 14, "Page Titles", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(31, 58, 58)
    _mc(pdf,15, _latin1_safe(f"Current: {data.get('current_title','')}"))
    _mc(pdf,15, _latin1_safe(f"Suggested: {data.get('suggested_title','')}"))
    pdf.ln(10)

    # Suggested Rewrite
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(31, 95, 95)
    pdf.cell(0, 20, "Suggested Rewrite", new_x="LMARGIN", new_y="NEXT")
    _render_markdown_to_pdf(pdf, data.get("rewrite_markdown", ""))
    pdf.ln(10)

    # Recommendations
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(31, 95, 95)
    pdf.cell(0, 20, "Recommendations", new_x="LMARGIN", new_y="NEXT")
    recs = data.get("recommendations", [])
    if not recs:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(31, 58, 58)
        _mc(pdf,15, "No recommendations.")
    else:
        for r in recs:
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(74, 127, 167)
            label = r.get("type", "").replace("_", " ").upper()
            pdf.cell(0, 12, _latin1_safe(label), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(31, 58, 58)
            _mc(pdf,14, _latin1_safe(r.get("note", "")))
            pdf.ln(4)

    # Broken Links (if checked)
    link_results = data.get("_link_results")
    if link_results is not None:
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(31, 95, 95)
        pdf.cell(0, 20, "Broken Links", new_x="LMARGIN", new_y="NEXT")
        broken = [r for r in link_results if r.get("status", 0) == 0 or r.get("status", 0) >= 400]
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(31, 58, 58)
        if not broken:
            _mc(pdf, 14, f"All {len(link_results)} links checked are working.")
        else:
            _mc(pdf, 14, f"{len(broken)} of {len(link_results)} links need attention:")
            pdf.ln(4)
            for r in broken:
                s = r.get("status", 0)
                label = (r.get("note") or "failed") if s == 0 else str(s)
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(201, 123, 90)
                pdf.cell(0, 12, _latin1_safe(f"[{label}] {r.get('text','')}"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(90, 117, 117)
                _mc(pdf, 12, _latin1_safe(r.get("url", "")))
                pdf.ln(3)

    # Footer
    pdf.ln(12)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(90, 117, 117)
    _mc(pdf,12, "Created by Kristen Hassen of Outcomes for Pets.  outcomesforpets.com")

    out = pdf.output()
    return bytes(out) if not isinstance(out, bytes) else out


def _render_markdown_to_pdf(pdf, md: str):
    """Minimal markdown renderer for fpdf2: headings, bullets, numbered lists, blockquotes, paragraphs, bold."""
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(31, 58, 58)
    lines = md.split("\n")
    in_bq = False
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            pdf.ln(4)
            continue
        if line.startswith("> "):
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(44, 74, 102)
            _mc(pdf,14, _latin1_safe(line[2:]))
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(31, 58, 58)
            continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(31, 95, 95)
            _mc(pdf,18, _latin1_safe(line[2:]))
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(31, 58, 58)
            continue
        if line.startswith("## "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(31, 95, 95)
            _mc(pdf,17, _latin1_safe(line[3:]))
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(31, 58, 58)
            continue
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(31, 95, 95)
            _mc(pdf,15, _latin1_safe(line[4:]))
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(31, 58, 58)
            continue
        if re.match(r"^\s*[-*]\s+", line):
            item = re.sub(r"^\s*[-*]\s+", "", line)
            _mc(pdf,14, f"  - {_strip_md(item)}")
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            item = re.sub(r"^\s*\d+\.\s+", "", line)
            _mc(pdf,14, f"  - {_strip_md(item)}")
            continue
        _mc(pdf,14, _strip_md(line))


def _strip_md(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    return _latin1_safe(s)


_PDF_REPLACEMENTS = {
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2018": "'", "\u2019": "'",     # curly single quotes
    "\u201c": '"', "\u201d": '"',     # curly double quotes
    "\u2026": "...",                  # ellipsis
    "\u00a0": " ",                    # non-breaking space
    "\u2022": "- ",                   # bullet
    "\u2713": "*", "\u2714": "*",     # check marks
    "\u2716": "x",                    # cross
    "\u26a0": "!",                    # warning sign
    "\u2696": "",                     # scales (legal)
    "\u270d": "",                     # writing hand
    "\u2705": "*",                    # white heavy check mark
    "\u274c": "x",                    # cross mark
    "\u2139": "i",                    # information
    "\u2728": "*",                    # sparkles
    "\u1f4a1": "*",                   # light bulb (shouldn't encode, but just in case)
}


def _latin1_safe(s):
    if not s:
        return ""
    for k, v in _PDF_REPLACEMENTS.items():
        s = s.replace(k, v)
    # Any remaining non-latin-1 chars get dropped
    return s.encode("latin-1", errors="replace").decode("latin-1").replace("?", "?")


def send_pdf_email(to_email: str, pdf_bytes: bytes, page_url: str, report_url: str):
    """Email the PDF as an attachment via Resend."""
    if not RESEND_API_KEY:
        app.logger.info(f"[email skipped] Would have emailed PDF to {to_email}")
        return False, "Email is not configured."
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": FROM_EMAIL,
                "to": [to_email],
                "subject": "Your website rewrite",
                "html": f"""
                    <p>Thanks for using <strong>Rewrite My Website</strong>.</p>
                    <p>Attached is a PDF of your rewrite for <a href="{html_escape(page_url)}">{html_escape(page_url)}</a>.</p>
                    <p>You can also view it online here: <a href="{html_escape(report_url)}">{html_escape(report_url)}</a></p>
                    <p style="color:#5a7575; font-size:14px;">Full-site rewrites are coming soon. Reply to this email if you'd like early access.</p>
                """,
                "attachments": [{
                    "filename": "website-rewrite.pdf",
                    "content": base64.b64encode(pdf_bytes).decode("ascii"),
                }],
            },
            timeout=30,
        )
        if resp.status_code >= 300:
            app.logger.warning(f"Resend error {resp.status_code}: {resp.text}")
            return False, f"Email service returned error ({resp.status_code})."
        return True, "Sent."
    except Exception as e:
        app.logger.warning(f"Failed to send email: {e}")
        return False, "Failed to send email."


def html_escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_client_ip():
    # Render sets X-Forwarded-For
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"

esc = html_escape

# ==================== ROUTES ====================

@app.route("/")
def index():
    return render_template_string(INDEX_HTML, css=PAGE_CSS, error=None, notice=None, daily_limit=DAILY_LIMIT)

@app.route("/review", methods=["POST"])
def review():
    email = (request.form.get("email") or "").strip()
    url = (request.form.get("url") or "").strip()
    ip = get_client_ip()

    if not email or "@" not in email:
        return render_template_string(INDEX_HTML, css=PAGE_CSS, error="Please enter a valid email.", notice=None, daily_limit=DAILY_LIMIT)
    if not url.startswith(("http://", "https://")):
        return render_template_string(INDEX_HTML, css=PAGE_CSS, error="Please enter a valid URL starting with http:// or https://", notice=None, daily_limit=DAILY_LIMIT)

    allowed, remaining = check_rate_limit(ip)
    if not allowed:
        return render_template_string(
            INDEX_HTML, css=PAGE_CSS,
            error=f"You've reached today's free limit of {DAILY_LIMIT} pages. Please check back tomorrow. Full-site rewrites are coming soon. Reply to our email to join the waitlist.",
            notice=None, daily_limit=DAILY_LIMIT,
        )

    check_links_flag = bool(request.form.get("check_links"))
    try:
        data = review_page(url, check_links_flag=check_links_flag)
    except Exception as e:
        app.logger.exception("Review failed")
        return render_template_string(
            INDEX_HTML, css=PAGE_CSS,
            error=f"We couldn't review that page. Please check the URL and try again. ({type(e).__name__})",
            notice=None, daily_limit=DAILY_LIMIT,
        )

    report_id = secrets.token_urlsafe(8)
    data["_email"] = email
    report_path = REPORTS / f"{report_id}.json"
    report_path.write_text(json.dumps(data))

    record_usage(ip)
    save_email(email, url, report_id, ip)

    return redirect(url_for("report", report_id=report_id))

@app.route("/report/<report_id>")
def report(report_id):
    # sanitize
    if not re.match(r"^[A-Za-z0-9_-]+$", report_id):
        abort(404)
    path = REPORTS / f"{report_id}.json"
    if not path.exists():
        abort(404)
    data = json.loads(path.read_text())
    status = request.args.get("status", "")
    status_msg = ""
    status_kind = ""
    if status == "sent":
        status_msg = f"Sent. Check {data.get('_email', 'your inbox')} for the PDF."
        status_kind = "success"
    elif status == "noemail":
        status_msg = "No email on file for this report."
        status_kind = "error"
    elif status == "pdffail":
        status_msg = "We couldn't generate the PDF. Try again, or copy the rewrite text instead."
        status_kind = "error"
    elif status == "emailfail":
        status_msg = "We couldn't send the email. Please try again shortly."
        status_kind = "error"
    return render_template_string(
        REPORT_HTML,
        css=PAGE_CSS,
        report_id=report_id,
        current_title=esc(data.get("current_title", "")),
        suggested_title=esc(data.get("suggested_title", "")),
        url=esc(data["_url"]),
        summary=esc(data.get("summary", "")),
        page_type=esc(data.get("page_type", "")),
        rewrite_html=markdown_to_html(data.get("rewrite_markdown", "")),
        rewrite_plain=data.get("rewrite_markdown", ""),
        recommendations=data.get("recommendations", []),
        original_text=esc(data["_original_text"]),
        email=esc(data.get("_email", "")),
        status_msg=status_msg,
        status_kind=status_kind,
        link_results=data.get("_link_results"),
    )

@app.route("/email-pdf/<report_id>", methods=["POST"])
def email_pdf(report_id):
    if not re.match(r"^[A-Za-z0-9_-]+$", report_id):
        abort(404)
    path = REPORTS / f"{report_id}.json"
    if not path.exists():
        abort(404)
    data = json.loads(path.read_text())
    email = data.get("_email")
    if not email:
        return redirect(url_for("report", report_id=report_id, status="noemail"))
    try:
        pdf_bytes = generate_pdf_bytes(data)
    except Exception as e:
        app.logger.exception("PDF generation failed")
        return redirect(url_for("report", report_id=report_id, status="pdffail"))
    base = BASE_URL or request.host_url.rstrip("/")
    report_url = f"{base}/report/{report_id}"
    ok, _ = send_pdf_email(email, pdf_bytes, data["_url"], report_url)
    return redirect(url_for("report", report_id=report_id, status="sent" if ok else "emailfail"))


@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
