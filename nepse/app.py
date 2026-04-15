from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy
from datetime import date, timedelta
import requests
import random
import pandas as pd
from bs4 import BeautifulSoup
import io
import threading
import time
import logging
import datetime as dt
import os
from functools import wraps
from typing import Any, Callable, Optional

from models import db, User, Holding, PendingSettlement, Transaction, Order, Watchlist, Holiday
from trading_engine import NepseTradingEngine, holiday_calendar

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if os.environ.get("FLASK_DEBUG", "false").lower() == "true" else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///nepse_sim.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

db.init_app(app)

# Global DataFrame for market data
df = pd.DataFrame()
df_lock = threading.Lock()
scraping_session = requests.Session()

# Whether market is always open (for testing)
DEBUG_MARKET_OPEN = os.environ.get("DEBUG_MARKET_OPEN", "true").lower() == "true"

# Rate limiting: simple in-memory tracker
_request_times: dict[str, list[float]] = {}
RL_WINDOW = 60  # seconds
RL_MAX_REQUESTS = 120


def rate_limit(f: Callable[..., Any]) -> Callable[..., Any]:
    """Simple per-IP rate limiter."""
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from flask import request, jsonify
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        now = time.time()
        times = _request_times.setdefault(ip, [])
        times[:] = [t for t in times if now - t < RL_WINDOW]
        if len(times) >= RL_MAX_REQUESTS:
            return jsonify({"success": False, "message": "Rate limit exceeded. Try again later."}), 429
        times.append(now)
        return f(*args, **kwargs)
    return wrapper


# ─── App Setup ─────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

    # Create default user if not exists
    if not User.query.first():
        default_user = User(
            username="default_user",
            virtual_cash=100000.0,
            investor_type="INDIVIDUAL",
        )
        db.session.add(default_user)
        db.session.commit()
        logger.info("Created default user with NPR 100,000 virtual cash.")

    # Sync holidays from engine to database
    for cal_date, name in holiday_calendar._holidays.items():
        if not Holiday.query.filter_by(date=cal_date).first():
            holiday = Holiday(date=cal_date, name=name)
            db.session.add(holiday)
    db.session.commit()


# ─── Scraper ──────────────────────────────────────────────────────────────────

def fetch_data_from_website() -> Optional[pd.DataFrame]:
    """Scrapes market data from ShareSansar."""
    url = "https://www.sharesansar.com/today-share-price"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Referer": url,
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        logger.debug("Fetching market data...")
        response = scraping_session.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            logger.error(f"Failed to fetch market data: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")

        for table in tables:
            try:
                table_dfs = pd.read_html(io.StringIO(str(table)))
                if not table_dfs:
                    continue
                new_df = table_dfs[0]
                new_df = new_df.loc[:, ~new_df.columns.duplicated()]

                symbol_col = next(
                    (c for c in new_df.columns if "SYMBOL" in c.upper()), None
                )
                if not symbol_col:
                    continue

                if symbol_col != "Symbol":
                    new_df.rename(columns={symbol_col: "Symbol"}, inplace=True)

                name_mapping = {
                    "LTP": "LTP",
                    "HIGH": "High",
                    "LOW": "Low",
                    "OPEN": "Open",
                    "PREV": "Prev. Close",
                    "DIFF": "Diff",
                    "%": "Diff %",
                }
                for col in new_df.columns:
                    for k, v in name_mapping.items():
                        if k in col.upper():
                            new_df.rename(columns={col: v}, inplace=True)
                            break
                return new_df
            except Exception as e:
                logger.debug(f"Table parse error: {e}")
                continue

    except Exception as e:
        logger.exception(f"Scraper error: {e}")
    return None


def scrape_worker() -> None:
    """Background thread to update market data."""
    global df
    while True:
        new_data = fetch_data_from_website()
        if new_data is not None:
            with df_lock:
                df = new_data
            logger.info("Market data updated successfully.")
        else:
            logger.warning("Market data fetch failed.")

        time.sleep(60)  # Update every 60 seconds


worker_thread = threading.Thread(target=scrape_worker, daemon=True)
worker_thread.start()


def order_worker() -> None:
    """Background thread to check and execute limit/stop-loss orders."""
    while True:
        try:
            with app.app_context():
                _process_pending_orders()
        except Exception as e:
            logger.exception("Error in order worker")
        time.sleep(10)  # Check every 10 seconds


def _process_pending_orders() -> None:
    """Process all open limit and stop-loss orders."""
    now = dt.datetime.now()
    today = now.date()

    open_orders = Order.query.filter_by(status="OPEN").all()

    for order in open_orders:
        # Check expiry
        if order.expires_at and now > order.expires_at:
            order.status = "EXPIRED"
            db.session.commit()
            logger.info(f"Order {order.id} ({order.symbol} {order.side}) expired.")
            continue

        # Get current price
        symbol_data = get_symbol_data(order.symbol)
        if not symbol_data:
            continue

        ltp = symbol_data["ltp"]
        triggered = False

        if order.order_type == "LIMIT":
            if order.side == "BUY" and ltp <= order.price:
                triggered = True
            elif order.side == "SELL" and ltp >= order.price:
                triggered = True
        elif order.order_type == "STOP_LOSS":
            if order.side == "SELL" and ltp <= order.price:
                triggered = True
            elif order.side == "BUY" and ltp >= order.price:
                triggered = True

        if not triggered:
            continue

        # Execute the order at current LTP
        user = User.query.get(order.user_id)
        if not user:
            order.status = "CANCELLED"
            db.session.commit()
            continue

        exec_price = ltp

        if order.side == "BUY":
            fees = NepseTradingEngine.calculate_fees(order.qty, exec_price, "BUY")
            if user.virtual_cash < fees["total_paid"]:
                logger.warning(f"Order {order.id} skipped: insufficient cash")
                continue
            user.virtual_cash -= fees["total_paid"]

            holding = Holding.query.filter_by(user_id=user.id, symbol=order.symbol).first()
            if holding:
                holding.total_qty += order.qty
                holding.settled_qty += order.qty
                new_qty = holding.total_qty
                new_cost = holding.total_cost_basis + fees["total_paid"]
                holding.wacc = round(new_cost / new_qty, 2)
                holding.total_cost_basis = round(new_cost, 2)
            else:
                holding = Holding(
                    user_id=user.id,
                    symbol=order.symbol,
                    total_qty=order.qty,
                    settled_qty=order.qty,
                    wacc=round(fees["total_paid"] / order.qty, 2),
                    total_cost_basis=round(fees["total_paid"], 2),
                    purchase_date=today,
                )
                db.session.add(holding)

            settle_date = NepseTradingEngine.calculate_settle_date(today)
            txn = Transaction(
                user_id=user.id,
                symbol=order.symbol,
                type="BUY",
                qty=order.qty,
                price=exec_price,
                gross=fees["gross"],
                commission=fees["commission"],
                sebon_fee=fees["sebon"],
                dp_fee=fees["dp"],
                total_fees=fees["total_fees"],
                total_paid=fees["total_paid"],
                wacc=holding.wacc,
                trade_date=today,
                settle_date=settle_date,
            )
            db.session.add(txn)
            logger.info(f"Limit BUY executed: {order.symbol} {order.qty} @ {exec_price}")

        else:  # SELL
            holding = Holding.query.filter_by(user_id=user.id, symbol=order.symbol).first()
            if not holding or holding.settled_qty < order.qty:
                logger.warning(f"Order {order.id} skipped: insufficient settled shares")
                continue

            cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
                order.qty, exec_price, holding.wacc,
                holding.purchase_date, today, user.investor_type
            )
            fees = NepseTradingEngine.calculate_fees(order.qty, exec_price, "SELL")
            user.virtual_cash += cgt_info["net_received"]

            new_total = holding.total_qty - order.qty
            if new_total == 0:
                db.session.delete(holding)
            else:
                holding.total_qty = new_total
                holding.settled_qty = max(0, holding.settled_qty - order.qty)

            txn = Transaction(
                user_id=user.id,
                symbol=order.symbol,
                type="SELL",
                qty=order.qty,
                price=exec_price,
                gross=fees["gross"],
                commission=fees["commission"],
                sebon_fee=fees["sebon"],
                dp_fee=fees["dp"],
                total_fees=fees["total_fees"],
                cgt=cgt_info["cgt"],
                net_received=cgt_info["net_received"],
                wacc=holding.wacc if new_total > 0 else 0.0,
                holding_days=cgt_info["holding_days"],
                trade_date=today,
                settle_date=today,
            )
            db.session.add(txn)
            logger.info(f"Limit SELL executed: {order.symbol} {order.qty} @ {exec_price}")

        order.status = "EXECUTED"
        order.executed_at = now
        db.session.commit()


order_thread = threading.Thread(target=order_worker, daemon=True)
order_thread.start()


# ─── Helpers ───────────────────────────────────────────────────────────────────

def get_current_user() -> Optional[User]:
    return User.query.first()


def process_settlements(user: User) -> None:
    """Process pending T+2 settlements."""
    today = date.today()
    pending = (
        PendingSettlement.query.filter_by(user_id=user.id, status="PENDING")
        .filter(PendingSettlement.settle_date <= today)
        .all()
    )
    for p in pending:
        holding = Holding.query.filter_by(user_id=user.id, symbol=p.symbol).first()
        if holding:
            holding.settled_qty += p.qty
        p.status = "SETTLED"
    if pending:
        db.session.commit()


def get_market_price(symbol: str) -> Optional[float]:
    """Get current LTP for a symbol."""
    with df_lock:
        if df.empty:
            return None
        row = df[df["Symbol"] == symbol]
        if not row.empty:
            try:
                return float(str(row.iloc[0]["LTP"]).replace(",", "").strip())
            except (ValueError, KeyError):
                return None
    return None


def get_prev_close(symbol: str) -> Optional[float]:
    """Get previous close price for a symbol."""
    with df_lock:
        if df.empty:
            return None
        row = df[df["Symbol"] == symbol]
        if not row.empty:
            try:
                return float(str(row.iloc[0]["Prev. Close"]).replace(",", "").strip())
            except (ValueError, KeyError):
                return None
    return None


def get_symbol_data(symbol: str) -> Optional[dict[str, Any]]:
    """Get full price data for a symbol."""
    with df_lock:
        if df.empty:
            return None
        row = df[df["Symbol"] == symbol]
        if row.empty:
            return None
        try:
            r = row.iloc[0]
            ltp = float(str(r["LTP"]).replace(",", "").strip())
            prev = float(str(r["Prev. Close"]).replace(",", "").strip())
            high = float(str(r.get("High", prev)).replace(",", "").strip())
            low = float(str(r.get("Low", prev)).replace(",", "").strip())
            upper, lower = NepseTradingEngine.calculate_price_band(prev)
            return {
                "ltp": ltp,
                "prev_close": prev,
                "high": high,
                "low": low,
                "upper_circuit": upper,
                "lower_circuit": lower,
            }
        except (ValueError, KeyError):
            return None


def clean_df_for_template(include_df: pd.DataFrame) -> pd.DataFrame:
    """Return a cleaned copy of the market DataFrame for template use."""
    with df_lock:
        if include_df.empty:
            return pd.DataFrame()
        clean = include_df.loc[:, ~include_df.columns.duplicated()].copy()
        clean["Diff %"] = pd.to_numeric(
            clean["Diff %"].astype(str).str.replace("%", "").str.replace(",", ""),
            errors="coerce",
        )
        return clean


def holdings_data_for_user(user: User) -> list[dict[str, Any]]:
    """Build portfolio holdings data with live prices."""
    holdings_data = []
    with df_lock:
        if df.empty:
            return holdings_data
        for holding in user.holdings:
            try:
                row = df[df["Symbol"] == holding.symbol]
                if row.empty:
                    continue
                ltp = float(str(row.iloc[0]["LTP"]).replace(",", "").strip())
                prev = float(str(row.iloc[0]["Prev. Close"]).replace(",", "").strip())
                diff_pct = ((ltp - prev) / prev * 100) if prev > 0 else 0.0
                unrealized_pl = (ltp * holding.total_qty) - holding.total_cost_basis
                holdings_data.append(
                    {
                        "symbol": holding.symbol,
                        "total_qty": holding.total_qty,
                        "settled_qty": holding.settled_qty,
                        "pending_qty": holding.total_qty - holding.settled_qty,
                        "wacc": holding.wacc,
                        "cost_basis": holding.total_cost_basis,
                        "ltp": ltp,
                        "current_value": ltp * holding.total_qty,
                        "unrealized_pl": unrealized_pl,
                        "unrealized_pl_pct": (
                            (unrealized_pl / holding.total_cost_basis * 100)
                            if holding.total_cost_basis > 0
                            else 0.0
                        ),
                        "diff_pct": diff_pct,
                        "is_odd_lot": holding.total_qty % 10 != 0,
                    }
                )
            except Exception as e:
                logger.error(f"Error processing holding {holding.symbol}: {e}")
    return holdings_data


# ─── Context Processor ─────────────────────────────────────────────────────────

@app.context_processor
def inject_user_stats() -> dict[str, Any]:
    """Inject global portfolio stats into all templates."""
    user = get_current_user()
    if not user:
        return {}

    process_settlements(user)

    total_investment = 0.0
    current_equity = 0.0

    with df_lock:
        if not df.empty:
            for holding in user.holdings:
                total_investment += holding.total_cost_basis
                try:
                    row = df[df["Symbol"] == holding.symbol]
                    if not row.empty:
                        ltp = float(str(row.iloc[0]["LTP"]).replace(",", "").strip())
                        current_equity += ltp * holding.total_qty
                except Exception:
                    pass

    net_worth = user.virtual_cash + current_equity
    day_gain = current_equity - total_investment
    day_gain_pct = (day_gain / total_investment * 100) if total_investment > 0 else 0.0

    return {
        "global_user": user,
        "global_net_worth": net_worth,
        "global_day_gain": day_gain,
        "global_day_gain_pct": day_gain_pct,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index() -> Any:
    user = get_current_user()
    process_settlements(user)

    holdings_data = holdings_data_for_user(user)
    pending_settlements = [
        p.to_dict()
        for p in (
            PendingSettlement.query.filter_by(user_id=user.id, status="PENDING")
            .order_by(PendingSettlement.settle_date)
            .all()
        )
    ]

    total_equity = sum(h["current_value"] for h in holdings_data)
    total_investment = sum(h["cost_basis"] for h in holdings_data)
    total_unrealized_pl = sum(h["unrealized_pl"] for h in holdings_data)
    total_portfolio_value = user.virtual_cash + total_equity

    # Top movers
    top_gainers = []
    top_losers = []
    clean = clean_df_for_template(df)
    if not clean.empty:
        top_gainers = clean.nlargest(5, "Diff %").to_dict("records")
        top_losers = clean.nsmallest(5, "Diff %").to_dict("records")

    return render_template(
        "index.html",
        user=user,
        holdings=holdings_data,
        pending_settlements=pending_settlements,
        total_equity=total_equity,
        total_investment=total_investment,
        total_unrealized_pl=total_unrealized_pl,
        total_portfolio_value=total_portfolio_value,
        top_gainers=top_gainers,
        top_losers=top_losers,
    )


@app.route("/marketmgmt/")
def market_index() -> Any:
    """Market explorer with all stocks."""
    user = get_current_user()
    with df_lock:
        table_dict = df.loc[:, ~df.columns.duplicated()].to_dict("records") if not df.empty else []
    watchlist_symbols = [
        item.symbol for item in Watchlist.query.filter_by(user_id=user.id).all()
    ]
    return render_template(
        "marketmgmt/index.html",
        table_data=table_dict,
        user=user,
        watchlist_symbols=watchlist_symbols,
    )


@app.route("/ordermgmt/")
def order_index() -> Any:
    """Trading terminal - Buy/Sell."""
    user = get_current_user()
    recent_transactions = (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.timestamp.desc())
        .limit(5)
        .all()
    )
    with df_lock:
        table_dict = (
            df.loc[:, ~df.columns.duplicated()].to_dict("records") if not df.empty else []
        )
    return render_template(
        "ordermgmt/index.html",
        table_data=table_dict,
        user=user,
        recent_transactions=recent_transactions,
    )


@app.route("/ordermgmt/history")
def order_history() -> Any:
    """Full transaction history."""
    user = get_current_user()
    transactions = (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )
    return render_template(
        "ordermgmt/history.html", user=user, transactions=transactions
    )


@app.route("/ordermgmt/orders")
def order_book() -> Any:
    """Open orders view."""
    user = get_current_user()
    orders = (
        Order.query.filter_by(user_id=user.id, status="OPEN")
        .order_by(Order.created_at.desc())
        .all()
    )
    return render_template("ordermgmt/orders.html", user=user, orders=orders)


@app.route("/api/market_data")
@rate_limit
def api_market_data() -> Any:
    """Get market data for all symbols."""
    with df_lock:
        if df.empty:
            return jsonify({"symbols": [], "data": {}})

        clean_df = df.loc[:, ~df.columns.duplicated()].copy()
        symbols = clean_df["Symbol"].tolist()
        data = {}

        for _, row in clean_df.iterrows():
            try:
                sym = row["Symbol"]
                ltp = float(str(row["LTP"]).replace(",", "").strip())
                prev = float(str(row["Prev. Close"]).replace(",", "").strip())
                high = float(str(row.get("High", prev)).replace(",", "").strip())
                low = float(str(row.get("Low", prev)).replace(",", "").strip())
                upper, lower = NepseTradingEngine.calculate_price_band(prev)
                data[sym] = {
                    "ltp": ltp,
                    "prev_close": prev,
                    "high": high,
                    "low": low,
                    "upper_circuit": upper,
                    "lower_circuit": lower,
                }
            except (ValueError, KeyError):
                continue

    return jsonify({"symbols": symbols, "data": data})


@app.route("/api/market_status")
@rate_limit
def api_market_status() -> Any:
    """Get current market open/close status."""
    if DEBUG_MARKET_OPEN:
        return jsonify({"is_open": True, "message": "Market is Open (Debug Mode).", "phase": "REGULAR"})
    is_open, msg, phase = NepseTradingEngine.is_market_open()
    return jsonify({"is_open": is_open, "message": msg, "phase": phase})


@app.route("/api/calculate/buy", methods=["POST"])
@rate_limit
def api_calculate_buy() -> Any:
    """Calculate buy order fees and WACC preview."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON body"})
    try:
        price = float(data.get("price", 0))
        qty = int(data.get("quantity", 0))
        symbol = str(data.get("symbol", "")).strip().upper()
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid price or quantity format"})
    if price <= 0 or qty <= 0:
        return jsonify({"success": False, "message": "Price and quantity must be positive"})
    if not symbol:
        return jsonify({"success": False, "message": "Symbol is required"})

    fees = NepseTradingEngine.calculate_fees(qty, price, "BUY")
    slab_info = NepseTradingEngine.get_slab_info(fees["gross"])

    user = get_current_user()
    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
    new_wacc = None
    if holding:
        new_wacc = round(
            (holding.total_cost_basis + fees["total_paid"])
            / (holding.total_qty + qty),
            2,
        )

    break_even = None
    if new_wacc:
        break_even = NepseTradingEngine.calculate_break_even(
            new_wacc, holding.total_qty + qty if holding else qty, user.investor_type
        )

    return jsonify(
        {
            "success": True,
            "fees": fees,
            "slab": slab_info,
            "new_wacc": new_wacc,
            "break_even": break_even,
        }
    )


@app.route("/api/calculate/sell", methods=["POST"])
@rate_limit
def api_calculate_sell() -> Any:
    """Calculate sell order proceeds and CGT."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON body"})
    try:
        price = float(data.get("price", 0))
        qty = int(data.get("quantity", 0))
        symbol = str(data.get("symbol", "")).strip().upper()
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid price or quantity format"})
    if price <= 0 or qty <= 0:
        return jsonify({"success": False, "message": "Price and quantity must be positive"})
    if not symbol:
        return jsonify({"success": False, "message": "Symbol is required"})

    user = get_current_user()
    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
    if not holding:
        return jsonify({"success": False, "message": "You do not own this stock"})

    if qty > holding.settled_qty:
        return jsonify(
            {
                "success": False,
                "message": f"Only {holding.settled_qty} shares settled. "
                f"{holding.total_qty - holding.settled_qty} pending T+2 settlement.",
            }
        )

    fees = NepseTradingEngine.calculate_fees(qty, price, "SELL")
    slab_info = NepseTradingEngine.get_slab_info(fees["gross"])
    cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
        qty, price, holding.wacc, holding.purchase_date, date.today(), user.investor_type
    )
    return jsonify({"success": True, "fees": fees, "slab": slab_info, "cgt": cgt_info})


@app.route("/api/execute/buy", methods=["POST"])
@rate_limit
def api_execute_buy() -> Any:
    """Execute an immediate buy order at LTP."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON body"})
    try:
        symbol = str(data.get("symbol", "")).strip().upper()
        price = float(data.get("price", 0))
        qty = int(data.get("quantity", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid order parameters"})

    if not symbol or price <= 0 or qty <= 0:
        return jsonify({"success": False, "message": "Invalid order parameters"})

    user = get_current_user()
    prev_close = get_prev_close(symbol)
    if not prev_close:
        return jsonify({"success": False, "message": f"Cannot find price data for {symbol}"})

    is_valid, msg = NepseTradingEngine.validate_price(price, prev_close)
    if not is_valid:
        return jsonify({"success": False, "message": msg})

    if not DEBUG_MARKET_OPEN:
        is_open, msg, _ = NepseTradingEngine.is_market_open()
        if not is_open:
            return jsonify({"success": False, "message": msg})

    fees = NepseTradingEngine.calculate_fees(qty, price, "BUY")
    total_required = fees["total_paid"]

    if user.virtual_cash < total_required:
        return jsonify(
            {
                "success": False,
                "message": (
                    f"Insufficient funds. Required: NPR {total_required:,.2f}, "
                    f"Available: NPR {user.virtual_cash:,.2f}"
                ),
            }
        )

    trade_date = dt.datetime.now()
    settle_date = NepseTradingEngine.calculate_settle_date(trade_date.date())
    user.virtual_cash -= total_required

    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
    if holding:
        old_qty = holding.total_qty
        old_cost = holding.total_cost_basis
        new_cost = fees["total_paid"]
        new_qty = old_qty + qty
        holding.total_qty = new_qty
        holding.wacc = round((old_cost + new_cost) / new_qty, 2)
        holding.total_cost_basis = round(old_cost + new_cost, 2)
        holding.settled_qty = new_qty
    else:
        holding = Holding(
            user_id=user.id,
            symbol=symbol,
            total_qty=qty,
            settled_qty=qty,
            wacc=round(fees["total_paid"] / qty, 2),
            total_cost_basis=round(fees["total_paid"], 2),
            purchase_date=trade_date.date(),
        )
        db.session.add(holding)

    txn = Transaction(
        user_id=user.id,
        symbol=symbol,
        type="BUY",
        qty=qty,
        price=price,
        gross=fees["gross"],
        commission=fees["commission"],
        sebon_fee=fees["sebon"],
        dp_fee=fees["dp"],
        total_fees=fees["total_fees"],
        total_paid=fees["total_paid"],
        wacc=holding.wacc if holding else 0.0,
        trade_date=trade_date.date(),
        settle_date=settle_date,
    )
    db.session.add(txn)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "message": f"Bought {qty} shares of {symbol} @ NPR {price}",
            "trade": txn.to_dict(),
        }
    )


@app.route("/api/execute/sell", methods=["POST"])
@rate_limit
def api_execute_sell() -> Any:
    """Execute an immediate sell order at LTP."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON body"})
    try:
        symbol = str(data.get("symbol", "")).strip().upper()
        price = float(data.get("price", 0))
        qty = int(data.get("quantity", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid order parameters"})

    if not symbol or price <= 0 or qty <= 0:
        return jsonify({"success": False, "message": "Invalid order parameters"})

    user = get_current_user()
    prev_close = get_prev_close(symbol)
    if not prev_close:
        return jsonify({"success": False, "message": f"Cannot find price data for {symbol}"})

    is_valid, msg = NepseTradingEngine.validate_price(price, prev_close)
    if not is_valid:
        return jsonify({"success": False, "message": msg})

    if not DEBUG_MARKET_OPEN:
        is_open, msg, _ = NepseTradingEngine.is_market_open()
        if not is_open:
            return jsonify({"success": False, "message": msg})

    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
    if not holding:
        return jsonify({"success": False, "message": f"You don't own {symbol}"})

    if qty > holding.settled_qty:
        return jsonify(
            {
                "success": False,
                "message": (
                    f"Only {holding.settled_qty} shares available to sell. "
                    f"{holding.total_qty - holding.settled_qty} shares pending settlement."
                ),
            }
        )

    trade_date = dt.datetime.now()
    cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
        qty, price, holding.wacc, holding.purchase_date, trade_date.date(), user.investor_type
    )
    fees = NepseTradingEngine.calculate_fees(qty, price, "SELL")
    user.virtual_cash += cgt_info["net_received"]

    new_total = holding.total_qty - qty
    if new_total == 0:
        db.session.delete(holding)
    else:
        new_settled = holding.settled_qty - qty
        holding.total_qty = new_total
        holding.settled_qty = max(0, new_settled)

    txn = Transaction(
        user_id=user.id,
        symbol=symbol,
        type="SELL",
        qty=qty,
        price=price,
        gross=fees["gross"],
        commission=fees["commission"],
        sebon_fee=fees["sebon"],
        dp_fee=fees["dp"],
        total_fees=fees["total_fees"],
        cgt=cgt_info["cgt"],
        net_received=cgt_info["net_received"],
        wacc=holding.wacc if new_total > 0 else 0.0,
        holding_days=cgt_info["holding_days"],
        trade_date=trade_date.date(),
        settle_date=trade_date.date(),
    )
    db.session.add(txn)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "message": f"Sold {qty} shares of {symbol} @ NPR {price}",
            "trade": txn.to_dict(),
        }
    )


@app.route("/api/holdings")
@rate_limit
def api_holdings() -> Any:
    """Get user's holdings with current prices."""
    user = get_current_user()
    holdings = holdings_data_for_user(user)
    return jsonify({"holdings": holdings})


@app.route("/api/watchlist")
@rate_limit
def api_watchlist() -> Any:
    """Get user's watchlist with current prices."""
    user = get_current_user()
    watchlist = []
    with df_lock:
        if not df.empty:
            for w in Watchlist.query.filter_by(user_id=user.id).all():
                try:
                    row = df[df["Symbol"] == w.symbol]
                    if not row.empty:
                        ltp = float(str(row.iloc[0]["LTP"]).replace(",", "").strip())
                        diff = float(str(row.iloc[0]["Diff"]).replace(",", "").strip())
                        diff_pct = float(
                            str(row.iloc[0]["Diff %"])
                            .replace("%", "")
                            .replace(",", "")
                            .strip()
                        )
                        watchlist.append(
                            {"symbol": w.symbol, "ltp": ltp, "diff": diff, "diff_pct": diff_pct}
                        )
                except (ValueError, KeyError):
                    continue
    return jsonify({"watchlist": watchlist})


@app.route("/api/watchlist/<symbol>", methods=["POST"])
@rate_limit
def api_toggle_watchlist(symbol: str) -> Any:
    """Add or remove a symbol from the watchlist."""
    user = get_current_user()
    symbol = symbol.strip().upper()
    if not symbol:
        return jsonify({"success": False, "message": "Symbol required"})

    existing = Watchlist.query.filter_by(user_id=user.id, symbol=symbol).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"success": True, "action": "removed", "symbol": symbol})

    new_watch = Watchlist(user_id=user.id, symbol=symbol)
    db.session.add(new_watch)
    db.session.commit()
    return jsonify({"success": True, "action": "added", "symbol": symbol})


@app.route("/api/orders", methods=["GET"])
@rate_limit
def api_get_orders() -> Any:
    """Get all open orders for the current user."""
    user = get_current_user()
    orders = [
        o.to_dict()
        for o in (
            Order.query.filter_by(user_id=user.id, status="OPEN")
            .order_by(Order.created_at.desc())
            .all()
        )
    ]
    return jsonify({"orders": orders})


@app.route("/api/orders", methods=["POST"])
@rate_limit
def api_place_order() -> Any:
    """Place a limit or stop-loss order."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON body"})

    try:
        symbol = str(data.get("symbol", "")).strip().upper()
        side = str(data.get("side", "")).strip().upper()
        order_type = str(data.get("order_type", "MARKET")).strip().upper()
        qty = int(data.get("quantity", 0))
        price = float(data.get("price", 0))
        validity = str(data.get("validity", "EOD")).strip().upper()
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid order parameters"})

    if not symbol or side not in ("BUY", "SELL") or qty <= 0 or price <= 0:
        return jsonify({"success": False, "message": "Invalid order parameters"})
    if order_type not in ("LIMIT", "STOP_LOSS"):
        return jsonify({"success": False, "message": "order_type must be LIMIT or STOP_LOSS"})
    if validity not in ("EOD", "GTC"):
        return jsonify({"success": False, "message": "validity must be EOD or GTC"})

    user = get_current_user()

    # Validate price band for limit/stop orders
    prev_close = get_prev_close(symbol)
    if not prev_close:
        return jsonify({"success": False, "message": f"Cannot find price for {symbol}"})
    is_valid, msg = NepseTradingEngine.validate_price(price, prev_close)
    if not is_valid:
        return jsonify({"success": False, "message": msg})

    # Market hours check
    if not DEBUG_MARKET_OPEN:
        is_open, msg, _ = NepseTradingEngine.is_market_open()
        if not is_open:
            return jsonify({"success": False, "message": msg})

    # Cash check for BUY
    if side == "BUY":
        fees = NepseTradingEngine.calculate_fees(qty, price, "BUY")
        if user.virtual_cash < fees["total_paid"]:
            return jsonify(
                {
                    "success": False,
                    "message": (
                        f"Insufficient funds. Required: NPR {fees['total_paid']:,.2f}, "
                        f"Available: NPR {user.virtual_cash:,.2f}"
                    ),
                }
            )

    # Settled qty check for SELL
    if side == "SELL":
        holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
        if not holding or holding.settled_qty < qty:
            avail = holding.settled_qty if holding else 0
            return jsonify(
                {
                    "success": False,
                    "message": f"Cannot sell {qty} shares. Available: {avail}",
                }
            )

    now = dt.datetime.now()
    expires_at = None
    if validity == "GTC":
        expires_at = now + timedelta(days=NepseTradingEngine.MAX_GTC_DAYS)
    else:
        expires_at = dt.datetime.combine(now.date(), time(15, 0))

    order = Order(
        user_id=user.id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        qty=qty,
        price=price,
        validity=validity,
        status="OPEN",
        created_at=now,
        expires_at=expires_at,
    )
    db.session.add(order)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "message": f"{side} {qty} {symbol} @ NPR {price} ({order_type}) order placed",
            "order": order.to_dict(),
        }
    )


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
@rate_limit
def api_cancel_order(order_id: int) -> Any:
    """Cancel an open order."""
    user = get_current_user()
    order = (
        Order.query.filter_by(id=order_id, user_id=user.id, status="OPEN")
        .first()
    )
    if not order:
        return jsonify({"success": False, "message": "Order not found or not open"})
    order.status = "CANCELLED"
    db.session.commit()
    return jsonify({"success": True, "message": f"Order {order_id} cancelled"})


@app.route("/api/calculator")
@rate_limit
def api_calculator() -> Any:
    """Break-even and profit/loss calculator."""
    symbol = request.args.get("symbol", "").strip().upper()
    qty = request.args.get("qty", type=int, default=0)
    buy_price = request.args.get("buy_price", type=float, default=0.0)
    sell_price = request.args.get("sell_price", type=float, default=0.0)

    if not symbol or qty <= 0 or buy_price <= 0:
        return jsonify({"success": False, "message": "Invalid parameters"})

    user = get_current_user()
    buy_fees = NepseTradingEngine.calculate_fees(qty, buy_price, "BUY")
    total_cost = buy_fees["total_paid"]
    wacc = round(total_cost / qty, 2)
    break_even = NepseTradingEngine.calculate_break_even(wacc, qty, user.investor_type)

    sell_info = {}
    if sell_price > 0:
        sell_fees = NepseTradingEngine.calculate_fees(qty, sell_price, "SELL")
        cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
            qty, sell_price, wacc, date.today() - timedelta(days=200), date.today(), user.investor_type
        )
        sell_info = {
            "sell_gross": sell_fees["gross"],
            "sell_fees": sell_fees["total_fees"],
            "cgt": cgt_info["cgt"],
            "net_received": cgt_info["net_received"],
            "profit": cgt_info["net_received"] - total_cost,
            "profit_pct": (
                (cgt_info["net_received"] - total_cost) / total_cost * 100
                if total_cost > 0
                else 0
            ),
        }

    return jsonify(
        {
            "success": True,
            "wacc": wacc,
            "total_cost": total_cost,
            "break_even": break_even,
            "buy_fees": buy_fees,
            "sell_info": sell_info,
        }
    )


@app.route("/api/market_index")
@rate_limit
def api_market_index() -> Any:
    """Simulated NEPSE index intraday data."""
    import random

    base_val = 2605.63
    points = []
    now = dt.datetime.now()
    start_time = now.replace(hour=11, minute=0, second=0, microsecond=0)
    curr_val = base_val
    for i in range(100):
        curr_val += random.uniform(-2, 2.5)
        points.append(
            {
                "time": (start_time + timedelta(minutes=i * 3)).strftime("%H:%M"),
                "value": round(curr_val, 2),
            }
        )
    return jsonify({"success": True, "data": points})


@app.route("/api/health")
def api_health() -> Any:
    """Health check endpoint for deployment."""
    return jsonify(
        {
            "status": "healthy",
            "market_data_rows": len(df) if not df.empty else 0,
            "market_open": DEBUG_MARKET_OPEN,
        }
    )


@app.route("/api/portfolio_performance")
@rate_limit
def api_portfolio_performance() -> Any:
    """Get cumulative portfolio value over time from transactions."""
    user = get_current_user()
    txns = (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.timestamp.asc())
        .all()
    )
    points = []
    running_cash = user.virtual_cash
    # Reconstruct cash at each point by walking backwards
    # For simplicity, we show cumulative P&L from starting capital
    starting_cash = 100000.0
    for txn in txns:
        if txn.type == "BUY":
            running_cash += txn.total_paid or 0
        else:
            running_cash -= txn.net_received or 0
        points.append(
            {
                "date": txn.timestamp.strftime("%Y-%m-%d"),
                "cash": round(running_cash, 2),
                "net_worth": round(running_cash, 2),  # Simplified
            }
        )
    return jsonify({"success": True, "data": points})


@app.route("/market-summary")
def market_summary() -> Any:
    """Market overview: index, movers, breadth."""
    clean = clean_df_for_template(df)
    top_gainers = clean.nlargest(10, "Diff %").to_dict("records") if not clean.empty else []
    top_losers = clean.nsmallest(10, "Diff %").to_dict("records") if not clean.empty else []

    # Market stats
    total = len(clean)
    advancers = len(clean[clean["Diff %"] > 0]) if not clean.empty else 0
    decliners = len(clean[clean["Diff %"] < 0]) if not clean.empty else 0
    unchanged = total - advancers - decliners

    # Volume leaders
    volume_col = next((c for c in clean.columns if "volume" in c.lower() or "qty" in c.lower()), None)
    top_volume = clean.nlargest(10, volume_col).to_dict("records") if volume_col and not clean.empty else []

    # Simulated index data for today
    index_history = []
    import random
    base_val = 2605.63
    now = dt.datetime.now()
    start = now.replace(hour=11, minute=0, second=0, microsecond=0)
    curr = base_val
    for i in range(60):
        curr += random.uniform(-3, 3.5)
        index_history.append({"time": (start + timedelta(minutes=i * 3)).strftime("%H:%M"), "value": round(curr, 2)})

    return render_template(
        "market_summary.html",
        top_gainers=top_gainers,
        top_losers=top_losers,
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        total_symbols=total,
        top_volume=top_volume,
        index_history=index_history,
    )


@app.route("/sector-analysis")
def sector_analysis() -> Any:
    """Sector performance heatmap and analysis."""
    clean = clean_df_for_template(df)
    # Group by sector (using symbol prefix as proxy, since sector data isn't in scraped table)
    # For demo, group by first 3 letters as sector
    if not clean.empty:
        clean["sector"] = clean["Symbol"].str[:3].map({
            "NBL": "Banking", "NIB": "Banking", "NICA": "Banking", "ADBL": "Banking",
            "SBI": "Banking", "MBL": "Banking", "KBL": "Banking", "PRVU": "Banking",
            "LBL": "Banking", "ICFC": "Finance", "MFIL": "Finance", "SBL": "Finance",
            "NEFI": "Finance", "SMF": "Finance", "GRAND": "Finance",
            "NTL": "Microfinance", "FOW": "Microfinance", "SKG": "Microfinance",
            "NMG": "Microfinance", "SMP": "Microfinance", "MMF": "Microfinance",
            "NHDL": "Hydropower", "NHPC": "Hydropower", "KPCL": "Hydropower",
            "AKPL": "Hydropower", "API": "Hydropower", "AKJCL": "Hydropower",
            "NCM": "Corporate", "UNL": "Corporate", "C": "Corporate",
            "NGPL": "Manufacturing", "JBBL": "Manufacturing",
            "SHIVM": "Trading", "SM": "Trading", "CG": "Trading",
            "NMB": "Commercial", "CEFL": "Commercial", "RLFL": "Commercial",
        }).fillna("Others")

        sector_stats = (
            clean.groupby("sector")
            .agg(
                count=("Symbol", "count"),
                avg_change=("Diff %", "mean"),
                total_volume=("Diff %", "sum"),
            )
            .reset_index()
            .sort_values("avg_change", ascending=False)
            .to_dict("records")
        )
    else:
        sector_stats = []

    return render_template("sector_analysis.html", sector_stats=sector_stats)


@app.route("/volume-analysis")
def volume_analysis() -> Any:
    """Volume charts and anomaly detection."""
    clean = clean_df_for_template(df)
    volume_col = next((c for c in clean.columns if "volume" in c.lower() or "qty" in c.lower()), None)
    if not clean.empty:
        clean["volume_val"] = pd.to_numeric(clean[volume_col].astype(str).str.replace(",", ""), errors="coerce") if volume_col else 0
        avg_vol = clean["volume_val"].mean()
        clean["vol_spike"] = clean["volume_val"] > avg_vol * 2
        high_volume = clean.nlargest(20, "volume_val").to_dict("records")
        vol_spikes = clean[clean["vol_spike"]].to_dict("records")
    else:
        high_volume = []
        vol_spikes = []
        avg_vol = 0

    # Simulated volume history
    vol_history = []
    now = dt.datetime.now()
    for i in range(30):
        vol_history.append({
            "date": (now - timedelta(days=29-i)).strftime("%Y-%m-%d"),
            "volume": int(random.uniform(50000, 500000)),
            "turnover": round(random.uniform(200, 800), 2),
        })

    import random
    return render_template("volume_analysis.html", high_volume=high_volume, vol_spikes=vol_spikes, avg_vol=avg_vol, vol_history=vol_history)


@app.route("/technical-analysis")
def technical_analysis() -> Any:
    """Technical indicators dashboard."""
    clean = clean_df_for_template(df)
    # Generate simulated technical data for top symbols
    import random
    symbols = clean.nlargest(20, "Diff %")["Symbol"].tolist() if not clean.empty else ["NABIL", "NBL", "ADBL", "NICL", "SCB"]
    tech_data = []
    for sym in symbols:
        row = clean[clean["Symbol"] == sym]
        ltp = float(str(row.iloc[0]["LTP"]).replace(",", "").strip()) if not row.empty else 0
        rsi = round(random.uniform(25, 80), 1)
        macd_signal = random.choice(["Bullish", "Bearish", "Neutral"])
        ma20 = ltp * random.uniform(0.95, 1.05)
        ma50 = ltp * random.uniform(0.90, 1.10)
        trend = "Uptrend" if ltp > ma20 else "Downtrend"
        tech_score = min(100, max(0, round((rsi / 100 * 40) + (50 if macd_signal == "Bullish" else 30))))
        tech_data.append({
            "symbol": sym, "ltp": ltp, "rsi": rsi, "macd": macd_signal,
            "ma20": round(ma20, 2), "ma50": round(ma50, 2),
            "trend": trend, "score": tech_score,
        })

    return render_template("technical_analysis.html", tech_data=tech_data)


@app.route("/watchlist-page")
def watchlist_page() -> Any:
    """Full watchlist page."""
    user = get_current_user()
    watchlist = []
    with df_lock:
        if not df.empty:
            for w in Watchlist.query.filter_by(user_id=user.id).all():
                try:
                    row = df[df["Symbol"] == w.symbol]
                    if not row.empty:
                        ltp = float(str(row.iloc[0]["LTP"]).replace(",", "").strip())
                        diff = float(str(row.iloc[0]["Diff"]).replace(",", "").strip())
                        diff_pct = float(str(row.iloc[0]["Diff %"]).replace("%", "").replace(",", "").strip())
                        vol_col = next((c for c in row.columns if "volume" in c.lower()), None)
                        vol = str(row.iloc[0][vol_col]) if vol_col else ""
                        watchlist.append({"symbol": w.symbol, "ltp": ltp, "diff": diff, "diff_pct": diff_pct, "volume": vol})
                except (ValueError, KeyError):
                    continue

    with df_lock:
        all_symbols = df["Symbol"].tolist() if not df.empty else []

    return render_template("watchlist.html", watchlist=watchlist, all_symbols=all_symbols)


@app.route("/charts")
@app.route("/charts/<symbol>")
def charts_page(symbol: Optional[str] = None) -> Any:
    """Charts page with TradingView widget."""
    if symbol is None:
        symbol = "NABIL"
    clean = clean_df_for_template(df)
    symbols = clean["Symbol"].tolist()[:50] if not clean.empty else ["NABIL", "NBL", "ADBL"]
    return render_template("charts.html", symbol=symbol.upper(), symbols=symbols)


@app.route("/signals")
def signals_page() -> Any:
    """AI trading signals page."""
    clean = clean_df_for_template(df)
    import random
    symbols = clean["Symbol"].tolist()[:30] if not clean.empty else ["NABIL", "NBL", "ADBL", "NICL", "SCB"]
    signals = []
    for sym in symbols:
        conf = round(random.uniform(55, 95), 1)
        signal_type = random.choice(["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"])
        if conf < 60:
            signal_type = "HOLD"
        price = float(str(clean[clean["Symbol"] == sym].iloc[0]["LTP"]).replace(",", "").strip()) if not clean.empty and sym in clean["Symbol"].values else 0
        signals.append({
            "symbol": sym, "type": signal_type, "confidence": conf,
            "price": price,
            "target": round(price * random.uniform(1.03, 1.15), 2),
            "stop_loss": round(price * random.uniform(0.90, 0.97), 2),
            "reasoning": f"{sym} showing {'bullish' if signal_type in ['BUY', 'STRONG_BUY'] else 'bearish'} momentum with RSI and MACD confirmation.",
            "timeframe": random.choice(["Short", "Medium", "Long"]),
            "generated": (dt.datetime.now() - timedelta(hours=random.randint(0, 12))).strftime("%Y-%m-%d %H:%M"),
        })

    # Sort by confidence
    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return render_template("signals.html", signals=signals)


@app.route("/broker-analysis")
def broker_analysis() -> Any:
    """Institutional broker activity page."""
    import random
    brokers = ["NMB Capital", "Nabil Invest", "World Trade Center", "Imel Securities", "Asia Securities", "Mercury Securities", "IDFC Investment", "股票 Capital"]
    sectors = ["Banking", "Hydropower", "Microfinance", "Finance", "Corporate", "Manufacturing"]
    activities = []
    now = dt.datetime.now()
    for i in range(30):
        activities.append({
            "broker": random.choice(brokers),
            "symbol": random.choice(["NABIL", "NBL", "ADBL", "NICL", "SCB", "NGPL", "NIBL", "KMCD"]),
            "type": random.choice(["BUY", "SELL"]),
            "quantity": random.randint(100, 5000) * 10,
            "price": round(random.uniform(500, 2000), 2),
            "value": round(random.uniform(100000, 5000000), 0),
            "sector": random.choice(sectors),
            "date": (now - timedelta(hours=random.randint(0, 72))).strftime("%Y-%m-%d %H:%M"),
        })

    # Top buyers/sellers
    top_buyers = [{"broker": b, "total": round(random.uniform(500000, 20000000), 0)} for b in random.sample(brokers, 4)]
    top_sellers = [{"broker": b, "total": round(random.uniform(500000, 20000000), 0)} for b in random.sample(brokers, 4)]
    top_buyers.sort(key=lambda x: x["total"], reverse=True)
    top_sellers.sort(key=lambda x: x["total"], reverse=True)

    return render_template("broker_analysis.html", activities=activities, top_buyers=top_buyers, top_sellers=top_sellers)


@app.route("/research-reports")
def research_reports() -> Any:
    """Research and reports page."""
    import random
    reports = [
        {"title": "NEPSE Market Outlook 2026", "category": "Market Analysis", "date": "2026-04-10", "summary": "Comprehensive analysis of NEPSE market trends, sector rotation patterns, and investment strategies for the year ahead.", "author": "Research Team", "views": 1245},
        {"title": "Banking Sector Deep Dive", "category": "Sector Report", "date": "2026-04-08", "summary": "Detailed analysis of Nepal's banking sector performance, NPL trends, and growth prospects in the post-pandemic era.", "author": "Research Team", "views": 892},
        {"title": "Hydropower Investment Guide", "category": "Investment Guide", "date": "2026-04-05", "summary": "Complete guide to investing in Nepal's hydropower sector, covering regulatory framework, project risks, and top picks.", "author": "Research Team", "views": 756},
        {"title": "Microfinance Sector Analysis", "category": "Sector Report", "date": "2026-04-01", "summary": "Assessment of microfinance companies' financial health, competition dynamics, and regulatory changes.", "author": "Research Team", "views": 543},
        {"title": "Technical Trading Strategies for NEPSE", "category": "Education", "date": "2026-03-28", "summary": "How to apply moving averages, RSI, and MACD on NEPSE stocks for better entry and exit timing.", "author": "Research Team", "views": 2103},
        {"title": "Q4 Earnings Season Review", "category": "Earnings", "date": "2026-03-25", "summary": "Quarterly earnings analysis of major NEPSE-listed companies with beat/miss assessment.", "author": "Research Team", "views": 687},
    ]
    categories = list(set(r["category"] for r in reports))
    return render_template("research_reports.html", reports=reports, categories=categories)


@app.route("/news")
def news_page() -> Any:
    """NEPSE news feed page."""
    import random
    news_items = [
        {"title": "NEPSE Index Surges 2.5% on Heavy Buying", "source": "ShareSansar", "date": "2026-04-15 10:30", "summary": "The NEPSE index gained significantly in today's trading session driven by heavy buying in banking and hydropower stocks.", "category": "Market", "symbols": ["NABIL", "NBL", "ADBL"]},
        {"title": "Nepal Government Announces New FDI Guidelines", "source": "Nepal Stock", "date": "2026-04-14 16:45", "summary": "The government has unveiled new foreign direct investment guidelines that may boost capital inflows into Nepal's stock market.", "category": "Policy", "symbols": []},
        {"title": "NABIL Reports 18% YoY Profit Growth", "source": "Company Filing", "date": "2026-04-14 09:00", "summary": "Nabil Bank reported strong quarterly results with net profit growing 18% year-over-year, beating analyst expectations.", "category": "Corporate", "symbols": ["NABIL"]},
        {"title": "SEBON Tightens Margin Trading Rules", "source": "SEBON", "date": "2026-04-13 14:20", "summary": "Securities Board of Nepal has introduced stricter margin trading regulations to curb speculative activity.", "category": "Regulatory", "symbols": []},
        {"title": "Hydropower Sector Sees Record Investment", "source": "Nepal Stock", "date": "2026-04-12 11:00", "summary": "Record NPR 50 billion invested in hydropower projects listed on NEPSE, signaling strong sector growth.", "category": "Sector", "symbols": ["NHPC", "KPCL"]},
        {"title": "NIC Asia Bank Merger Gets Board Approval", "source": "Company Filing", "date": "2026-04-11 15:30", "summary": "NIC Asia Bank's proposed merger with other entity has received board approval, awaiting regulatory clearance.", "category": "Corporate", "symbols": ["NICA"]},
        {"title": "NEPSE Daily Turnover Crosses NPR 1 Billion", "source": "ShareSansar", "date": "2026-04-10 16:00", "summary": "Daily market turnover exceeded NPR 1 billion for the first time this year, indicating improved market liquidity.", "category": "Market", "symbols": []},
        {"title": "Insurance Sector Regulatory Changes", "source": "Beema Samiti", "date": "2026-04-09 10:00", "summary": "New insurance regulations will impact how insurance companies operate and report on NEPSE.", "category": "Regulatory", "symbols": []},
    ]
    return render_template("news.html", news_items=news_items)


@app.route("/newsletter")
def newsletter_page() -> Any:
    """Newsletter signup page."""
    return render_template("newsletter.html")


@app.route("/trader-profile")
def trader_profile() -> Any:
    """Trader profile: portfolio, quiz, recommendations."""
    user = get_current_user()
    holdings = holdings_data_for_user(user)

    # Quiz questions
    quiz = [
        {"id": 1, "question": "What's your primary investment goal?", "options": ["Capital preservation", "Steady growth", "Aggressive returns", "Income generation"]},
        {"id": 2, "question": "How long do you plan to hold your investments?", "options": ["Intraday (< 1 day)", "Short-term (1 week - 3 months)", "Medium-term (3-12 months)", "Long-term (> 1 year)"]},
        {"id": 3, "question": "How would you react to a 20% portfolio drop?", "options": ["Sell immediately", "Hold and wait", "Buy more", "Invest elsewhere"]},
        {"id": 4, "question": "Your experience level?", "options": ["Beginner", "Intermediate", "Advanced", "Professional"]},
    ]

    # Recommendations based on quiz
    recommendations = [
        {"symbol": "NABIL", "name": "Nabil Bank", "score": 85, "reason": "Strong fundamentals, consistent dividends, low volatility"},
        {"symbol": "NICL", "name": "NIC Asia Life", "score": 78, "reason": "Growing premiums, expanding distribution network"},
        {"symbol": "NIBL", "name": "NIBL Pragya", "score": 72, "reason": "Diversified mutual fund, good for beginners"},
    ]

    # Stats
    total_trades = Transaction.query.filter_by(user_id=user.id).count()
    buy_trades = Transaction.query.filter_by(user_id=user.id, type="BUY").count()
    sell_trades = Transaction.query.filter_by(user_id=user.id, type="SELL").count()

    return render_template(
        "trader_profile.html",
        user=user,
        holdings=holdings,
        quiz=quiz,
        recommendations=recommendations,
        total_trades=total_trades,
        buy_trades=buy_trades,
        sell_trades=sell_trades,
    )


# ─── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    logger.info(f"Starting NEPSE Virtual Trading on port {port}, debug={debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
