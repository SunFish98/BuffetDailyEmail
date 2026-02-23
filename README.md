# SICA — Sage Investor Council Agent

A multi-agent stock analysis system that uses Claude AI to simulate 7 legendary investors analyzing the daily market, then aggregates their opinions into a single actionable intelligence report delivered to your inbox.

## How It Works

```
┌─────────────────────────────────────────────────┐
│            Daily Cron Trigger                    │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│         Agent 0: Data Collector                  │
│  Stock prices, news, earnings, SEC filings,      │
│  macro indicators, insider trading               │
└────────────────────┬────────────────────────────┘
                     ▼
    ┌────┬────┬────┬┴┬────┬────┬────┐
    ▼    ▼    ▼    ▼ ▼    ▼    ▼    │
 Buffett Munger Soros Lynch Dalio Icahn Graham
    │    │    │    │  │    │    │
    └────┴────┴──┬─┴──┴────┴────┘
                 ▼
┌─────────────────────────────────────────────────┐
│         Agent 8: Aggregator                      │
│  Finds consensus, flags disagreements,           │
│  synthesizes final action ideas                  │
└────────────────────┬────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────┐
│         Email Delivery + History Tracking         │
└─────────────────────────────────────────────────┘
```

## The 7 Sage Analysts

| Agent | Philosophy | Focus |
|---|---|---|
| **Warren Buffett** | Buy wonderful companies at fair prices, hold forever | Moats, owner earnings, ROE, management quality |
| **Charlie Munger** | Latticework of mental models, invert always invert | Checklists, avoiding stupidity, incentives analysis |
| **George Soros** | Reflexivity theory, boom-bust cycles | Macro, sentiment extremes, narrative shifts |
| **Peter Lynch** | Invest in what you know, growth at reasonable price | PEG ratio, stock categories, tenbaggers |
| **Ray Dalio** | All-weather thinking, debt cycles, risk parity | Economic machine, cycle positioning, correlations |
| **Carl Icahn** | Activist investing, find and fix mismanagement | Governance, breakup value, catalysts, buybacks |
| **Benjamin Graham** | Margin of safety, quantitative deep value | Graham number, P/E < 15, P/B < 1.5, net-nets |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```
ANTHROPIC_API_KEY=your_key_here    # Required
FRED_API_KEY=your_key_here         # Optional, for macro data
```

Only `ANTHROPIC_API_KEY` is required. The system uses free data sources (yfinance, Google News RSS) by default.

### 3. Customize your watchlist

Edit `config/settings.yaml` to add or remove tickers:

```yaml
watchlist:
  - AAPL
  - MSFT
  - GOOGL
  # ... add your tickers
```

### 4. Run

```bash
# Full run — all 7 sages (collect data → analyze → email report)
python run.py

# Generate report without sending email
python run.py --skip-email

# Don't save HTML/text report files
python run.py --no-save

# Run only specific analysts (saves API budget)
python run.py --analysts warren_buffett benjamin_graham charlie_munger
```

Reports are saved to `data/report_YYYY-MM-DD.html` and `data/report_YYYY-MM-DD.txt`.

### 5. Budget control — pick your sages

Each analyst = 1 Claude API call per run. Running all 7 costs ~7x a single call. To save budget, enable only the analysts you want in `config/settings.yaml`:

```yaml
analysts:
  enabled:
    - warren_buffett
    - benjamin_graham
    - charlie_munger
```

Or override from the command line (takes priority over config):

```bash
python run.py --analysts warren_buffett peter_lynch
```

Available analyst keys:

| Key | Sage |
|---|---|
| `warren_buffett` | Warren Buffett — value + moat investing |
| `charlie_munger` | Charlie Munger — mental models + inversion |
| `george_soros` | George Soros — reflexivity + macro |
| `peter_lynch` | Peter Lynch — GARP + PEG ratio |
| `ray_dalio` | Ray Dalio — cycles + risk parity |
| `carl_icahn` | Carl Icahn — activist + governance |
| `benjamin_graham` | Benjamin Graham — deep value + margin of safety |

When fewer than 7 analysts are active, the consensus threshold auto-adjusts so you still get meaningful consensus signals.

Omit the `enabled` key entirely (or delete it) to run all 7.

## Data Sources

### Free (no API key needed)

| Source | Data | Notes |
|---|---|---|
| **yfinance** | Stock prices, fundamentals, earnings | Default market data source |
| **Google News RSS** | Financial news per ticker | Default news source |
| **SEC EDGAR** | 10-K, 10-Q, 8-K, Form 4 filings | Requires email for User-Agent |

### Free with API key

| Source | Data | Get Key |
|---|---|---|
| **FRED** | 15 macro indicators (Fed rate, CPI, GDP, VIX, etc.) | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| **Finnhub** | News, earnings calendar, insider trading | [finnhub.io](https://finnhub.io/) |
| **NewsAPI** | Additional news coverage | [newsapi.org](https://newsapi.org/) |

### Paid (optional upgrades)

| Source | Data | Notes |
|---|---|---|
| **Alpha Vantage** | Market data + company overview | Free tier: 25 req/day |
| **Polygon.io** | Market data | Free tier: 5 req/min |

Set `market_data_source` in `config/settings.yaml` to switch between providers.

## Email Setup

### Gmail (SMTP)

1. Enable 2-Factor Authentication on your Google account
2. Generate an [App Password](https://myaccount.google.com/apppasswords)
3. Add to `.env`:

```
EMAIL_METHOD=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@example.com
```

### SendGrid

```
EMAIL_METHOD=sendgrid
SENDGRID_API_KEY=your_key
EMAIL_FROM=your_email@example.com
EMAIL_TO=recipient@example.com
```

Also uncomment `sendgrid` in `requirements.txt` and run `pip install sendgrid`.

## Scheduling

The system is designed to run once daily after market close. Set up a cron job, GitHub Actions workflow, or any scheduler:

```bash
# Cron example: run at 5:30 PM ET every weekday
30 17 * * 1-5 cd /path/to/sica && python run.py
```

## Configuration Reference

All settings live in `config/settings.yaml`:

| Setting | Default | Description |
|---|---|---|
| `watchlist` | 35 tickers | Stocks to analyze |
| `data_collection.market_data_source` | `yfinance` | `yfinance`, `alpha_vantage`, or `polygon` |
| `data_collection.price_history_days` | `30` | Days of price history to include |
| `data_collection.max_news_per_ticker` | `5` | News articles per stock |
| `analysts.model` | `claude-sonnet-4-20250514` | Claude model for analysis |
| `analysts.parallel` | `true` | Run all 7 analysts concurrently |
| `analysts.temperature` | `0.3` | LLM temperature (0=deterministic) |
| `aggregator.consensus_threshold` | `3` | Minimum analysts for "consensus" label |
| `history.track_accuracy` | `true` | Track recommendation accuracy over time |

## Historical Tracking

The system stores every recommendation in SQLite (`data/history.db`) with the price at time of recommendation. Over time it builds an accuracy scorecard for each analyst, included in the daily email.

## Project Structure

```
sica/
├── config/settings.yaml              # Watchlist + all settings
├── .env.example                      # API keys template
├── requirements.txt                  # Python dependencies
├── run.py                            # Entry point
├── src/
│   ├── main.py                       # 5-phase orchestrator
│   ├── data_collector/
│   │   ├── collector.py              # Data collection orchestrator
│   │   ├── market_data.py            # yfinance / Alpha Vantage / Polygon
│   │   ├── news.py                   # Google RSS / Finnhub / NewsAPI
│   │   ├── earnings.py              # Earnings history + calendar
│   │   ├── macro.py                  # FRED API (15 macro indicators)
│   │   ├── sec_filings.py           # SEC EDGAR filings
│   │   └── insider.py               # Insider trading activity
│   ├── analysts/
│   │   ├── base.py                   # Claude API integration + JSON output
│   │   ├── buffett.py               # Warren Buffett agent
│   │   ├── munger.py                # Charlie Munger agent
│   │   ├── soros.py                 # George Soros agent
│   │   ├── lynch.py                 # Peter Lynch agent
│   │   ├── dalio.py                 # Ray Dalio agent
│   │   ├── icahn.py                 # Carl Icahn agent
│   │   └── graham.py               # Benjamin Graham agent
│   ├── aggregator/aggregator.py     # Consensus + LLM synthesis
│   ├── email_sender/sender.py       # HTML/text email delivery
│   └── storage/history.py           # SQLite tracking + scorecards
└── data/                             # Reports + history database
```

## Disclaimer

SICA generates AI-simulated investment analysis for **educational and informational purposes only**. It is **not financial advice**. The AI agents simulate investment philosophies but are not the actual investors. Always do your own research and consult a qualified financial advisor before making investment decisions.
