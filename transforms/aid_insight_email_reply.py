"""
aidinsight_email_reply.py — AI-powered email response generator for AidInsight.

Paste an inbound training enquiry email into the clipboard.
The transform:
  1. Fetches aidinsight.com.au for current course/workshop context
  2. Calls the Anthropic API to draft a professional reply
  3. Returns YAML with two keys:
       response: the ready-to-send email reply
       context:  the full conversation context for follow-up questions

Output format:
    response: |
      <email response>
    context: |
      <original prompt and email response>

Requirements:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import os
import subprocess
import yaml

# ── Configuration ─────────────────────────────────────────────────────────────

MODEL        = "claude-opus-4-6"
MAX_TOKENS   = 2048
SITE_URL     = "https://aidinsight.com.au"
COURSES_URL  = "https://aidinsight.com.au/courses/"

# ── Business context (static, supplements live site fetch) ────────────────────

BUSINESS_CONTEXT = """
AidInsight is a Perth-based mental health training organisation run by Senior
Mental Health Clinicians and Master Instructors in Mental Health First Aid.

Key facts:
- All courses delivered by TWO senior mental health professionals (unique differentiator)
- 140+ years of combined clinical mental health nursing experience
- Accredited Mental Health First Aid (MHFA) courses: Standard, Youth, Older Person,
  Aboriginal and Torres Strait Islander
- Refresher courses available for all accredited MHFA streams
- AidInsight-branded courses: Mental Health Toolkit, Calming Conflict & De-Escalating Aggression
- Workshops for adults: Depression & Suicide, Anxiety & Self-Injury, Alcohol & Other Drugs,
  Emotional First Aid, Menopause, Retirement, Trauma-Centered Education, and more
- Student workshops for ages 12+
- Delivery: metropolitan Perth, regional, remote Western Australia, and beyond
- Flexible options: tailored to timeframes and budgets
- Contact: info@aidinsight.com.au
- Public courses held at Kardinya Lesser Hall, Morris Buzzacott Reserve, 51 Williamson Road

Tone: warm, professional, clinically credible, encouraging. Not overly corporate.
Always sign off from the AidInsight team, not as an individual.
"""

# ─────────────────────────────────────────────────────────────────────────────

def _fetch_site_text(url: str, max_chars: int = 3000) -> str:
    """Fetch a URL via curl and return plain text (best effort)."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "10", "-L", url],
            capture_output=True, text=True, timeout=15
        )
        raw = result.stdout
        # Very basic HTML strip — remove tags
        import re
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as exc:
        return f"[site fetch failed: {exc}]"


def transform(text: str) -> str:
    try:
        import anthropic
    except ImportError:
        return _yaml_error("anthropic package not installed. Run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _yaml_error(
            "ANTHROPIC_API_KEY environment variable not set.\n"
            "Export it before launching ClipCommand:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-..."
        )

    email_prompt = text.strip()
    if not email_prompt:
        return _yaml_error("Clipboard is empty — paste the inbound email first.")

    # Fetch live site content for course details
    site_text    = _fetch_site_text(SITE_URL)
    courses_text = _fetch_site_text(COURSES_URL)

    system_prompt = f"""You are a professional email assistant for AidInsight, a mental health
training organisation based in Perth, Western Australia.

BUSINESS CONTEXT:
{BUSINESS_CONTEXT}

LIVE WEBSITE CONTENT (homepage):
{site_text}

LIVE WEBSITE CONTENT (courses page):
{courses_text}

YOUR TASK:
Draft a warm, professional email reply to the inbound enquiry provided by the user.
- Use the website and business context above to give accurate, specific information
- Always mention the two-senior-clinicians differentiator where relevant
- Offer to discuss requirements further and invite them to contact info@aidinsight.com.au
- Keep the reply concise but complete — aim for 150-250 words
- Do NOT invent prices, dates, or details not present in the context
- Sign off as: The AidInsight Team

Return ONLY the email body text — no subject line, no markdown formatting."""

    user_message = f"Please reply to this inbound training enquiry:\n\n{email_prompt}"

    try:
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model      = MODEL,
            max_tokens = MAX_TOKENS,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_message}]
        )
        reply = response.content[0].text.strip()
    except Exception as exc:
        return _yaml_error(f"Anthropic API error: {exc}")

    # Build context for follow-up questions
    context_block = (
        f"=== ORIGINAL ENQUIRY ===\n{email_prompt}\n\n"
        f"=== AIDINSIGHT RESPONSE ===\n{reply}\n\n"
        f"=== BUSINESS CONTEXT ===\n{BUSINESS_CONTEXT.strip()}"
    )

    # Serialise to YAML
    try:
        output = yaml.dump(
            {"response": reply, "context": context_block},
            default_flow_style=False,
            allow_unicode=True,
            width=10000,   # prevent line wrapping inside values
        )
        return output.strip()
    except Exception as exc:
        return _yaml_error(f"YAML serialisation error: {exc}")


def _yaml_error(message: str) -> str:
    """Return a valid YAML error payload."""
    return yaml.dump(
        {"response": f"[aidinsight_email_reply error]\n{message}", "context": ""},
        default_flow_style=False,
        allow_unicode=True,
    ).strip()