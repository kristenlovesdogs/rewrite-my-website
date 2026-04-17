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
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    <form method="POST" action="/review">
      <label for="email">Your email</label>
      <input type="email" id="email" name="email" required placeholder="you@rescue.org">

      <label for="url">Page URL to review</label>
      <input type="url" id="url" name="url" required placeholder="https://yourshelter.org/adopt">

      <div style="margin-top: 20px;">
        <button type="submit">Review this page</button>
      </div>
      <div class="fineprint">
        Free: one page at a time. We'll email your rewrite as soon as it's ready.
        Limit {{ daily_limit }} pages per day. <strong>Full-site rewrites coming soon.</strong>
      </div>
    </form>
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
  <div class="rewrite">{{ rewrite_html|safe }}</div>

  <h2>Recommendations</h2>
  <div class="recs">
    {% for r in recommendations %}
    <div class="rec"><span class="rec-type {{ r.type }}">{{ r.type.replace('_',' ') }}</span>{{ r.note }}</div>
    {% else %}
    <p>No recommendations.</p>
    {% endfor %}
  </div>

  <h2>Original Text</h2>
  <button onclick="document.getElementById('orig').classList.toggle('shown')">Show / Hide Original</button>
  <div class="original" id="orig">{{ original_text }}</div>

  <div style="margin-top:40px;"><a href="/" class="btn">← Review another page</a></div>
</div>

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

def send_report_email(to_email: str, report_url: str, page_url: str):
    """Send report link via Resend. No-op if RESEND_API_KEY is not set."""
    if not RESEND_API_KEY:
        app.logger.info(f"[email skipped] Would have emailed {to_email} with {report_url}")
        return
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": FROM_EMAIL,
                "to": [to_email],
                "subject": "Your website rewrite is ready",
                "html": f"""
                    <p>Thanks for using <strong>Rewrite My Website</strong>.</p>
                    <p>Your rewrite for <a href="{page_url}">{page_url}</a> is ready:</p>
                    <p><a href="{report_url}" style="background:#2d8a8a;color:white;padding:10px 18px;text-decoration:none;border-radius:6px;display:inline-block;">View your rewrite</a></p>
                    <p style="color:#5a7575;font-size:14px;">Full-site rewrites are coming soon. Reply to this email if you'd like early access.</p>
                """,
            },
            timeout=15,
        )
        if resp.status_code >= 300:
            app.logger.warning(f"Resend error {resp.status_code}: {resp.text}")
    except Exception as e:
        app.logger.warning(f"Failed to send email: {e}")

def get_client_ip():
    # Render sets X-Forwarded-For
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

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

    try:
        data = review_page(url)
    except Exception as e:
        app.logger.exception("Review failed")
        return render_template_string(
            INDEX_HTML, css=PAGE_CSS,
            error=f"We couldn't review that page. Please check the URL and try again. ({type(e).__name__})",
            notice=None, daily_limit=DAILY_LIMIT,
        )

    report_id = secrets.token_urlsafe(8)
    report_path = REPORTS / f"{report_id}.json"
    report_path.write_text(json.dumps(data))

    record_usage(ip)
    save_email(email, url, report_id, ip)

    base = BASE_URL or request.host_url.rstrip("/")
    report_url = f"{base}/report/{report_id}"
    send_report_email(email, report_url, url)

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
    return render_template_string(
        REPORT_HTML,
        css=PAGE_CSS,
        current_title=esc(data.get("current_title", "")),
        suggested_title=esc(data.get("suggested_title", "")),
        url=esc(data["_url"]),
        summary=esc(data.get("summary", "")),
        page_type=esc(data.get("page_type", "")),
        rewrite_html=markdown_to_html(data.get("rewrite_markdown", "")),
        recommendations=data.get("recommendations", []),
        original_text=esc(data["_original_text"]),
    )

@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
