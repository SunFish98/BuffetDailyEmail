"""Email formatting and sending."""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Template

logger = logging.getLogger(__name__)

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<style>
  body { font-family: 'Georgia', serif; background: #f5f5f0; margin: 0; padding: 20px; }
  .container { max-width: 700px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
  .header { background: #1a1a2e; color: white; padding: 30px; text-align: center; }
  .header h1 { margin: 0; font-size: 24px; letter-spacing: 1px; }
  .header .date { color: #a0a0c0; margin-top: 8px; font-size: 14px; }
  .section { padding: 20px 30px; border-bottom: 1px solid #eee; }
  .section h2 { color: #1a1a2e; font-size: 18px; margin-top: 0; border-left: 4px solid #e63946; padding-left: 12px; }
  .section h3 { color: #333; font-size: 15px; margin-bottom: 5px; }
  .overview { background: #f8f9fa; padding: 15px 20px; border-radius: 6px; line-height: 1.6; color: #333; }
  .pick { background: #f8f9fa; border-radius: 6px; padding: 12px 16px; margin: 10px 0; border-left: 4px solid #2ecc71; }
  .pick.sell { border-left-color: #e74c3c; }
  .pick.debate { border-left-color: #f39c12; }
  .pick .ticker { font-weight: bold; font-size: 16px; color: #1a1a2e; }
  .pick .analysts { color: #666; font-size: 13px; margin: 4px 0; }
  .pick .reasoning { color: #444; font-size: 14px; line-height: 1.5; }
  .action-idea { background: #eaf4fc; border-radius: 6px; padding: 12px 16px; margin: 10px 0; }
  .action-idea .idea { font-weight: bold; color: #1a1a2e; }
  .action-idea .rationale { color: #555; font-size: 14px; margin-top: 4px; }
  .action-idea .risk { color: #e74c3c; font-size: 13px; margin-top: 4px; }
  .risk-item { color: #c0392b; padding: 4px 0; font-size: 14px; }
  .analyst-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .analyst-table th { background: #1a1a2e; color: white; padding: 8px 12px; text-align: left; }
  .analyst-table td { padding: 8px 12px; border-bottom: 1px solid #eee; }
  .analyst-table tr:nth-child(even) { background: #f8f9fa; }
  .conviction-high { color: #27ae60; font-weight: bold; }
  .conviction-medium { color: #f39c12; }
  .conviction-low { color: #95a5a6; }
  .footer { padding: 20px 30px; text-align: center; color: #999; font-size: 12px; }
  .disclaimer { font-style: italic; color: #999; font-size: 11px; padding: 15px 30px; border-top: 1px solid #eee; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>DAILY INVESTMENT INTELLIGENCE</h1>
    <div class="date">{{ date }}</div>
  </div>

  <!-- Market Overview -->
  <div class="section">
    <h2>Market Overview</h2>
    <div class="overview">{{ synthesis.market_overview | default("No overview available.") }}</div>
  </div>

  <!-- Strongest Signals -->
  {% if synthesis.strongest_signals %}
  <div class="section">
    <h2>Strongest Signals</h2>
    {% for signal in synthesis.strongest_signals %}
    <div class="pick {% if signal.direction == 'SELL' %}sell{% endif %}">
      <span class="ticker">{{ signal.ticker }}</span>
      <span style="color: {% if signal.direction == 'BUY' %}#27ae60{% else %}#e74c3c{% endif %}; font-weight: bold;">
        {{ signal.direction }}
      </span>
      <span class="conviction-{{ signal.confidence | lower }}"> ({{ signal.confidence }})</span>
      <div class="reasoning">{{ signal.synthesis }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Consensus Buys -->
  {% if consensus_buys %}
  <div class="section">
    <h2>Consensus Buys ({{ consensus_threshold }}+ Analysts Agree)</h2>
    {% for cb in consensus_buys %}
    <div class="pick">
      <span class="ticker">{{ cb.ticker }}</span> &mdash;
      <span class="analysts">{{ cb.analysts | join(", ") }} ({{ cb.buy_count }} analysts)</span>
      {% for analyst, reason in cb.reasonings.items() %}
      <div class="reasoning"><strong>{{ analyst }}:</strong> {{ reason }}</div>
      {% endfor %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Consensus Sells -->
  {% if consensus_sells %}
  <div class="section">
    <h2>Consensus Sells / Avoids</h2>
    {% for cs in consensus_sells %}
    <div class="pick sell">
      <span class="ticker">{{ cs.ticker }}</span> &mdash;
      <span class="analysts">{{ cs.analysts | join(", ") }} ({{ cs.sell_count }} analysts)</span>
      {% for analyst, reason in cs.reasonings.items() %}
      <div class="reasoning"><strong>{{ analyst }}:</strong> {{ reason }}</div>
      {% endfor %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Interesting Debates -->
  {% if synthesis.interesting_debates %}
  <div class="section">
    <h2>Interesting Debates</h2>
    {% for debate in synthesis.interesting_debates %}
    <div class="pick debate">
      <span class="ticker">{{ debate.topic }}</span>
      <div class="reasoning"><strong>Bull Case:</strong> {{ debate.bull_case }}</div>
      <div class="reasoning"><strong>Bear Case:</strong> {{ debate.bear_case }}</div>
      <div class="reasoning"><em>{{ debate.implication }}</em></div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Action Ideas -->
  {% if synthesis.action_ideas %}
  <div class="section">
    <h2>Action Ideas</h2>
    {% for idea in synthesis.action_ideas %}
    <div class="action-idea">
      <div class="idea">{{ idea.idea }}</div>
      <div class="rationale">{{ idea.rationale }}</div>
      <div class="risk">Risk: {{ idea.risk }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Key Risks -->
  {% if synthesis.key_risks %}
  <div class="section">
    <h2>Key Risks to Watch</h2>
    {% for risk in synthesis.key_risks %}
    <div class="risk-item">&bull; {{ risk }}</div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Full Analyst Breakdown -->
  <div class="section">
    <h2>Full Analyst Breakdown</h2>
    <table class="analyst-table">
      <tr>
        <th>Analyst</th>
        <th>Ticker</th>
        <th>Action</th>
        <th>Conviction</th>
        <th>Reasoning</th>
      </tr>
      {% for result in analyst_results %}
        {% for pick in result.top_picks %}
        <tr>
          <td>{{ result.analyst }}</td>
          <td><strong>{{ pick.ticker }}</strong></td>
          <td style="color: {% if pick.action == 'BUY' %}#27ae60{% elif pick.action == 'SELL' %}#e74c3c{% else %}#f39c12{% endif %};">
            {{ pick.action }}
          </td>
          <td class="conviction-{{ pick.conviction | lower }}">{{ pick.conviction }}</td>
          <td>{{ pick.reasoning[:150] }}{% if pick.reasoning | length > 150 %}...{% endif %}</td>
        </tr>
        {% endfor %}
      {% endfor %}
    </table>
  </div>

  <!-- Accuracy Scorecard -->
  {% if scorecard %}
  <div class="section">
    <h2>Analyst Accuracy (Last {{ lookback_days }} Days)</h2>
    <table class="analyst-table">
      <tr>
        <th>Analyst</th>
        <th>Accuracy</th>
        <th>Avg Return</th>
        <th>Picks</th>
      </tr>
      {% for analyst, sc in scorecard.items() %}
      <tr>
        <td>{{ analyst }}</td>
        <td>{{ sc.accuracy_pct }}%</td>
        <td style="color: {% if sc.avg_return >= 0 %}#27ae60{% else %}#e74c3c{% endif %};">
          {{ sc.avg_return }}%
        </td>
        <td>{{ sc.total }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  <div class="disclaimer">
    This report is generated by AI agents simulating the investment philosophies of famous investors.
    It is for educational and informational purposes only. This is NOT financial advice.
    Always do your own research and consult a qualified financial advisor before making investment decisions.
  </div>

  <div class="footer">
    Generated by BuffetDailyEmail &bull; Multi-Agent Stock Analysis System
  </div>
</div>
</body>
</html>
"""

# Plain text version for email clients that don't support HTML
TEXT_TEMPLATE = """
═══════════════════════════════════════════
  DAILY INVESTMENT INTELLIGENCE BRIEFING
  {{ date }}
═══════════════════════════════════════════

MARKET OVERVIEW
{{ synthesis.market_overview | default("No overview available.") }}

{% if synthesis.strongest_signals %}
STRONGEST SIGNALS
{% for signal in synthesis.strongest_signals %}
  {{ signal.direction }} {{ signal.ticker }} ({{ signal.confidence }})
  {{ signal.synthesis }}
{% endfor %}
{% endif %}

{% if consensus_buys %}
CONSENSUS BUYS ({{ consensus_threshold }}+ analysts agree)
{% for cb in consensus_buys %}
  {{ cb.ticker }} — {{ cb.analysts | join(", ") }}
  {% for analyst, reason in cb.reasonings.items() %}
    {{ analyst }}: {{ reason }}
  {% endfor %}
{% endfor %}
{% endif %}

{% if consensus_sells %}
CONSENSUS SELLS
{% for cs in consensus_sells %}
  {{ cs.ticker }} — {{ cs.analysts | join(", ") }}
{% endfor %}
{% endif %}

{% if synthesis.action_ideas %}
ACTION IDEAS
{% for idea in synthesis.action_ideas %}
  {{ loop.index }}. {{ idea.idea }}
     {{ idea.rationale }}
     Risk: {{ idea.risk }}
{% endfor %}
{% endif %}

{% if synthesis.key_risks %}
KEY RISKS
{% for risk in synthesis.key_risks %}
  * {{ risk }}
{% endfor %}
{% endif %}

FULL ANALYST BREAKDOWN
{% for result in analyst_results %}
--- {{ result.analyst }} ---
Outlook: {{ result.market_outlook | default("N/A") }}
{% for pick in result.top_picks %}
  {{ pick.action }} {{ pick.ticker }} ({{ pick.conviction }}) — {{ pick.reasoning[:100] }}
{% endfor %}
{% endfor %}

═══════════════════════════════════════════
DISCLAIMER: This is AI-generated analysis for educational purposes only.
This is NOT financial advice. Do your own research.
═══════════════════════════════════════════
"""


class EmailSender:
    """Formats and sends the daily investment intelligence email."""

    def __init__(self, config: dict):
        self.config = config
        email_config = config.get("email", {})
        self.subject_template = email_config.get("subject", "Daily Investment Intelligence - {date}")
        self.send_if_no_signals = email_config.get("send_if_no_signals", True)

    def format_report(self, aggregated_report: dict, analyst_results: list[dict],
                      scorecard: dict | None = None, lookback_days: int = 30) -> tuple[str, str]:
        """Format the report as HTML and plain text.

        Returns:
            Tuple of (html_content, text_content)
        """
        today = datetime.now().strftime("%B %d, %Y")

        template_data = {
            "date": today,
            "synthesis": aggregated_report.get("synthesis", {}),
            "consensus_buys": aggregated_report.get("consensus_buys", []),
            "consensus_sells": aggregated_report.get("consensus_sells", []),
            "consensus_threshold": self.config.get("aggregator", {}).get("consensus_threshold", 3),
            "analyst_results": analyst_results,
            "scorecard": scorecard,
            "lookback_days": lookback_days,
        }

        html = Template(EMAIL_TEMPLATE).render(**template_data)
        text = Template(TEXT_TEMPLATE).render(**template_data)

        return html, text

    def send(self, html_content: str, text_content: str) -> bool:
        """Send the email using the configured method."""
        method = os.getenv("EMAIL_METHOD", "smtp")
        today = datetime.now().strftime("%Y-%m-%d")
        subject = self.subject_template.format(date=today)

        if method == "sendgrid":
            return self._send_sendgrid(subject, html_content, text_content)
        else:
            return self._send_smtp(subject, html_content, text_content)

    def _send_smtp(self, subject: str, html: str, text: str) -> bool:
        """Send email via SMTP."""
        host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        port = int(os.getenv("SMTP_PORT", "587"))
        user = os.getenv("SMTP_USER", "")
        password = os.getenv("SMTP_PASSWORD", "")
        from_addr = os.getenv("EMAIL_FROM", user)
        to_addr = os.getenv("EMAIL_TO", "")

        if not all([user, password, to_addr]):
            logger.error("SMTP credentials not configured. Set SMTP_USER, SMTP_PASSWORD, EMAIL_TO in .env")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.sendmail(from_addr, to_addr.split(","), msg.as_string())

            logger.info(f"Email sent to {to_addr}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _send_sendgrid(self, subject: str, html: str, text: str) -> bool:
        """Send email via SendGrid API."""
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail, Content

            api_key = os.getenv("SENDGRID_API_KEY", "")
            from_addr = os.getenv("EMAIL_FROM", "")
            to_addr = os.getenv("EMAIL_TO", "")

            if not all([api_key, from_addr, to_addr]):
                logger.error("SendGrid not configured. Set SENDGRID_API_KEY, EMAIL_FROM, EMAIL_TO.")
                return False

            sg = sendgrid.SendGridAPIClient(api_key=api_key)
            message = Mail(
                from_email=from_addr,
                to_emails=to_addr,
                subject=subject,
                plain_text_content=Content("text/plain", text),
                html_content=Content("text/html", html),
            )
            response = sg.send(message)
            logger.info(f"SendGrid email sent: {response.status_code}")
            return response.status_code in (200, 202)
        except ImportError:
            logger.error("sendgrid package not installed. Run: pip install sendgrid")
            return False
        except Exception as e:
            logger.error(f"SendGrid send failed: {e}")
            return False

    def save_to_file(self, html_content: str, text_content: str, output_dir: str = "data"):
        """Save the report to files (useful for testing or archival)."""
        os.makedirs(output_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")

        html_path = os.path.join(output_dir, f"report_{today}.html")
        text_path = os.path.join(output_dir, f"report_{today}.txt")

        with open(html_path, "w") as f:
            f.write(html_content)
        with open(text_path, "w") as f:
            f.write(text_content)

        logger.info(f"Reports saved to {html_path} and {text_path}")
        return html_path, text_path
