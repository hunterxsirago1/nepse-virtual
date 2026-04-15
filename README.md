# NEPSE Virtual Trading Simulator

A realistic NEPSE (Nepal Stock Exchange) paper trading simulator with accurate trading rules, T+2 settlement, fee breakdowns, and a polished UI.

## Features

- **T+2 Settlement**: Shares bought today settle in 2 business days (weekends/holidays skipped)
- **No Intraday Trading**: Can only sell settled shares
- **Price Band**: ±10% circuit breaker validation
- **Full Fee Breakdown**: Commission (slab-based), SEBON, DP charges, CGT
- **CGT Calculation**: 7.5% (<365 days), 5% (≥365 days), 10% institutional
- **WACC**: Weighted Average Cost Capital tracking per NEPSE rules
- **Limit & Stop-Loss Orders**: Background job executes pending orders when price triggers
- **Market Orders**: Immediate execution at LTP
- **Watchlist**: Star symbols for quick tracking on dashboard
- **Market Explorer**: Full live data table with search and filtering
- **Transaction History**: Complete audit log with full fee/cost basis breakdown
- **Dark/Light Theme**: Toggle via sidebar button
- **Rate Limiting**: API protection against abuse

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
cd nepse
python app.py

# Or from project root
python -m nepse.app
```

Open http://localhost:5000 in your browser.

## Configuration

Copy `.env.example` to `.env` and set:

```bash
DEBUG_MARKET_OPEN=true    # Set false for real NEPSE hours
FLASK_DEBUG=false         # Set true for debug mode
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///nepse_sim.db  # Or use PostgreSQL
```

## Trading Rules

| Rule | Detail |
|------|--------|
| Market Hours | 11:00 AM - 3:00 PM NST (Mon-Fri) |
| Settlement | T+2 business days |
| Price Band | ±10% from previous close |
| Commission | 0.243%–0.36% (slab-based) |
| SEBON Fee | 0.015% of gross (buy & sell) |
| DP Charge | NPR 25 per transaction |
| CGT | 7.5% (<365d), 5% (≥365d), 10% institutional |
| Min Commission | NPR 10 per trade |

### Commission Slabs (on gross amount)

| Amount Range | Rate |
|---|---|
| Up to NPR 50,000 | 0.36% |
| NPR 50,001 – 500,000 | 0.33% |
| NPR 500,001 – 2,000,000 | 0.306% |
| NPR 2,000,001 – 10,000,000 | 0.27% |
| Above NPR 10,000,000 | 0.243% |

## Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard — portfolio, P&L, watchlist, movers |
| `/marketmgmt/` | Market Explorer — live data for all symbols |
| `/ordermgmt/` | Trading Terminal — buy/sell market, limit, stop-loss |
| `/ordermgmt/history` | Transaction History — full fee breakdown |
| `/ordermgmt/orders` | Open Orders — pending limit/stop orders |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/market_data` | GET | All symbols with price/circuit data |
| `/api/market_status` | GET | Market open/closed status |
| `/api/market_index` | GET | NEPSE index intraday chart data |
| `/api/holdings` | GET | User's portfolio with live prices |
| `/api/calculate/buy` | POST | Preview buy fees and WACC |
| `/api/calculate/sell` | POST | Preview sell proceeds and CGT |
| `/api/execute/buy` | POST | Execute immediate buy |
| `/api/execute/sell` | POST | Execute immediate sell |
| `/api/orders` | GET/POST | List or place limit/stop orders |
| `/api/orders/<id>` | DELETE | Cancel an open order |
| `/api/watchlist` | GET | User's watchlist |
| `/api/watchlist/<symbol>` | POST | Add/remove from watchlist |
| `/api/calculator` | GET | Break-even and P&L calculator |
| `/api/health` | GET | Health check endpoint |
| `/api/portfolio_performance` | GET | Cumulative portfolio history |

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=nepse --cov-report=term-missing
```

## Tech Stack

- **Backend**: Flask 3, SQLAlchemy, Pandas, BeautifulSoup
- **Frontend**: Vanilla JS, Chart.js, DataTables, FontAwesome
- **Database**: SQLite (default), PostgreSQL (production)
- **Data Source**: Scraped from ShareSansar.com

## Architecture

```
nepse/
├── app.py              # Flask app, routes, API endpoints
├── models.py           # SQLAlchemy models
├── trading_engine.py   # Fee/CGT/settlement logic
├── templates/
│   ├── base.html       # Shared layout + sidebar
│   ├── index.html      # Dashboard
│   ├── marketmgmt/     # Market explorer
│   └── ordermgmt/      # Trading, history, orders
├── static/
│   └── css/styles.css  # Design system
└── tests/             # pytest unit + integration tests
```
