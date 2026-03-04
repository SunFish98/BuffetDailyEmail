"""SICA Web Interface — Flask application."""

import json
import logging
import os
import threading
from datetime import datetime

import yaml
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash

load_dotenv()
logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "sica-dev-secret-change-in-production")

# ── Globals for background analysis ──
_analysis_status = {
    "running": False,
    "progress": "",
    "phase": 0,
    "total_phases": 5,
    "error": None,
    "completed_at": None,
}

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "history.db")


def _load_config():
    config_path = os.path.normpath(CONFIG_PATH)
    if os.path.exists(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def _save_config(config):
    config_path = os.path.normpath(CONFIG_PATH)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _load_env():
    """Load .env file as a dict."""
    env_path = os.path.normpath(ENV_PATH)
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()
    return env_vars


def _save_env(env_vars):
    """Save env vars to .env file, preserving comments."""
    env_path = os.path.normpath(ENV_PATH)
    # Read existing file to preserve comments and structure
    lines = []
    existing_keys = set()
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}\n")
                        existing_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

    # Add any new keys not in the file
    for key, value in env_vars.items():
        if key not in existing_keys and value:
            lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


def _get_history_tracker():
    from src.storage import HistoryTracker
    db = os.path.normpath(DB_PATH)
    return HistoryTracker(db_path=db)


def _get_all_reports():
    """Get all past reports from the database."""
    import sqlite3
    db = os.path.normpath(DB_PATH)
    if not os.path.exists(db):
        return []
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT date, created_at FROM daily_reports ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _get_report(date):
    """Get a specific report by date."""
    tracker = _get_history_tracker()
    return tracker.get_past_report(date)


# ── Analyst metadata ──
ANALYST_INFO = {
    "warren_buffett": {"name": "Warren Buffett", "short": "Value + Moat", "icon": "WB"},
    "charlie_munger": {"name": "Charlie Munger", "short": "Mental Models", "icon": "CM"},
    "george_soros": {"name": "George Soros", "short": "Reflexivity + Macro", "icon": "GS"},
    "peter_lynch": {"name": "Peter Lynch", "short": "GARP + PEG", "icon": "PL"},
    "ray_dalio": {"name": "Ray Dalio", "short": "Cycles + Risk Parity", "icon": "RD"},
    "carl_icahn": {"name": "Carl Icahn", "short": "Activist + Governance", "icon": "CI"},
    "benjamin_graham": {"name": "Benjamin Graham", "short": "Deep Value + Safety", "icon": "BG"},
}

# ══════════════════════════════════════════
# Routes
# ══════════════════════════════════════════


@app.route("/")
def dashboard():
    config = _load_config()
    reports = _get_all_reports()
    latest_report = None
    if reports:
        latest_report = _get_report(reports[0]["date"])

    env_vars = _load_env()
    provider = env_vars.get("LLM_PROVIDER", "anthropic").lower()
    if provider in ("google", "gemini"):
        has_api_key = bool(env_vars.get("GEMINI_API_KEY") and
                           env_vars["GEMINI_API_KEY"] != "your_gemini_api_key_here")
    else:
        has_api_key = bool(env_vars.get("ANTHROPIC_API_KEY") and
                           env_vars["ANTHROPIC_API_KEY"] != "your_anthropic_api_key_here")

    enabled = config.get("analysts", {}).get("enabled")
    enabled_count = len(enabled) if enabled else 7
    watchlist = config.get("watchlist", [])

    return render_template(
        "dashboard.html",
        status=_analysis_status,
        latest_report=latest_report,
        reports=reports[:5],
        has_api_key=has_api_key,
        enabled_count=enabled_count,
        watchlist_count=len(watchlist),
        total_reports=len(reports),
    )


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        return _handle_setup_save()

    config = _load_config()
    env_vars = _load_env()

    enabled = config.get("analysts", {}).get("enabled")
    enabled_keys = set(enabled) if enabled else set(ANALYST_INFO.keys())

    return render_template(
        "setup.html",
        config=config,
        env_vars=env_vars,
        analyst_info=ANALYST_INFO,
        enabled_keys=enabled_keys,
    )


def _handle_setup_save():
    config = _load_config()
    env_vars = _load_env()

    # LLM Provider
    llm_provider = request.form.get("LLM_PROVIDER", "anthropic").strip()
    env_vars["LLM_PROVIDER"] = llm_provider

    # API Keys
    for key in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "FRED_API_KEY", "FINNHUB_API_KEY",
                "NEWSAPI_KEY", "ALPHA_VANTAGE_API_KEY", "POLYGON_API_KEY"]:
        val = request.form.get(key, "").strip()
        if val:
            env_vars[key] = val

    # Email settings
    env_vars["EMAIL_METHOD"] = request.form.get("EMAIL_METHOD", "smtp")
    for key in ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                "EMAIL_FROM", "EMAIL_TO", "SENDGRID_API_KEY"]:
        val = request.form.get(key, "").strip()
        if val:
            env_vars[key] = val

    # Models
    model = request.form.get("CLAUDE_MODEL", "").strip()
    if model:
        env_vars["CLAUDE_MODEL"] = model
    gemini_model = request.form.get("GEMINI_MODEL", "").strip()
    if gemini_model:
        env_vars["GEMINI_MODEL"] = gemini_model

    _save_env(env_vars)

    # Watchlist
    watchlist_text = request.form.get("watchlist", "")
    tickers = [t.strip().upper() for t in watchlist_text.replace(",", "\n").split("\n") if t.strip()]
    if tickers:
        config["watchlist"] = tickers

    # Analysts
    enabled_analysts = request.form.getlist("analysts")
    if enabled_analysts and len(enabled_analysts) < 7:
        config.setdefault("analysts", {})["enabled"] = enabled_analysts
    else:
        # All selected = remove the key so all run
        config.get("analysts", {}).pop("enabled", None)

    # Data source
    source = request.form.get("market_data_source", "yfinance")
    config.setdefault("data_collection", {})["market_data_source"] = source

    _save_config(config)

    flash("Settings saved successfully.", "success")
    return redirect(url_for("setup"))


@app.route("/history")
def history():
    reports = _get_all_reports()
    scorecard = {}
    try:
        tracker = _get_history_tracker()
        scorecard = tracker.get_analyst_scorecard(lookback_days=30)
    except Exception:
        pass

    return render_template(
        "history.html",
        reports=reports,
        scorecard=scorecard,
    )


@app.route("/report/<date>")
def report_detail(date):
    report_data = _get_report(date)
    if not report_data:
        flash("Report not found.", "error")
        return redirect(url_for("history"))

    return render_template(
        "report.html",
        report=report_data,
        date=date,
    )


@app.route("/api/run", methods=["POST"])
def api_run_analysis():
    """Trigger an analysis run in the background."""
    if _analysis_status["running"]:
        return jsonify({"error": "Analysis already running"}), 409

    thread = threading.Thread(target=_run_analysis_background, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/status")
def api_status():
    """Get current analysis status."""
    return jsonify(_analysis_status)


@app.route("/api/report/<date>")
def api_report(date):
    """Get report data as JSON."""
    report = _get_report(date)
    if not report:
        return jsonify({"error": "Not found"}), 404
    return jsonify(report)


def _run_analysis_background():
    """Run the full analysis pipeline in a background thread."""
    global _analysis_status
    _analysis_status = {
        "running": True,
        "progress": "Starting analysis...",
        "phase": 0,
        "total_phases": 5,
        "error": None,
        "completed_at": None,
    }

    try:
        from src.data_collector import DataCollector
        from src.analysts import get_enabled_analysts, ALL_ANALYSTS
        from src.aggregator import Aggregator
        from src.email_sender import EmailSender
        from src.storage import HistoryTracker
        from src.main import run_analyst

        config = _load_config()
        watchlist = config.get("watchlist", [])

        # Phase 1
        _analysis_status["phase"] = 1
        _analysis_status["progress"] = f"Collecting market data for {len(watchlist)} tickers..."
        collector = DataCollector(config)
        data = collector.collect_all(watchlist)
        market_briefing = collector.prepare_full_context(data)

        # Phase 2
        _analysis_status["phase"] = 2
        enabled = get_enabled_analysts(config)
        _analysis_status["progress"] = f"Running {len(enabled)} analyst agents..."

        from concurrent.futures import ThreadPoolExecutor, as_completed
        analyst_results = []
        with ThreadPoolExecutor(max_workers=len(enabled)) as executor:
            futures = {
                executor.submit(run_analyst, cls, config, market_briefing): cls.name
                for cls in enabled
            }
            done = 0
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    analyst_results.append(result)
                except Exception as e:
                    analyst_results.append({
                        "analyst": name, "error": str(e),
                        "top_picks": [], "avoid_list": [],
                        "key_observations": [], "market_outlook": "Error",
                    })
                done += 1
                _analysis_status["progress"] = f"Analysts complete: {done}/{len(enabled)}"

        # Phase 3
        _analysis_status["phase"] = 3
        _analysis_status["progress"] = "Aggregating analyst opinions..."
        aggregator = Aggregator(config)
        aggregated = aggregator.aggregate(analyst_results, market_briefing)

        # Phase 4
        _analysis_status["phase"] = 4
        _analysis_status["progress"] = "Saving to history..."
        today = datetime.now().strftime("%Y-%m-%d")
        db_path = config.get("history", {}).get("db_path", "data/history.db")
        history = HistoryTracker(db_path=db_path)
        history.save_recommendations(today, analyst_results, data.get("market_data", {}))
        scorecard = history.get_analyst_scorecard(30)

        full_report = {
            "date": today,
            "analyst_results": analyst_results,
            "aggregated": aggregated,
            "scorecard": scorecard,
        }
        history.save_report(today, full_report)

        # Phase 5
        _analysis_status["phase"] = 5
        _analysis_status["progress"] = "Generating report..."
        email_sender = EmailSender(config)
        html, text = email_sender.format_report(aggregated, analyst_results, scorecard)
        email_sender.save_to_file(html, text)

        # Try sending email (non-fatal if it fails)
        try:
            email_sender.send(html, text)
        except Exception:
            pass

        _analysis_status["progress"] = "Analysis complete!"
        _analysis_status["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    except Exception as e:
        logger.error(f"Background analysis failed: {e}")
        _analysis_status["error"] = str(e)
        _analysis_status["progress"] = f"Error: {e}"
    finally:
        _analysis_status["running"] = False


def create_app():
    """Factory function for the Flask app."""
    return app
