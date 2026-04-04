import os
from flask import Flask, jsonify, render_template, request, flash, redirect, url_for, session
import requests
import pandas as pd
from bs4 import BeautifulSoup
import io
import threading
import time
import logging
import datetime
from dateutil.relativedelta import relativedelta

from models import db, User, Holding, PendingSettlement, Transaction, Order, Watchlist, Holiday
from trading_engine import (
    NepseTradingEngine, TradingAccount, OrderManager,
    holiday_calendar, HolidayCalendar
)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nepse_sim.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret-key'

db.init_app(app)

# Global DataFrame for market data
df = pd.DataFrame()
df_lock = threading.Lock()
scraping_session = requests.Session()

# Initialize default user and holidays
with app.app_context():
    db.create_all()

    # Create default user if not exists
    if not User.query.first():
        default_user = User(username='default_user', virtual_cash=100000.0, investor_type='INDIVIDUAL')
        db.session.add(default_user)
        db.session.commit()

    # Sync holidays from engine to database
    for date, name in holiday_calendar._holidays.items():
        if not Holiday.query.filter_by(date=date).first():
            holiday = Holiday(date=date, name=name)
            db.session.add(holiday)
    db.session.commit()


def fetch_data_from_website():
    """Scrapes market data from ShareSansar."""
    url = "https://www.sharesansar.com/today-share-price"
    ajax_url = "https://www.sharesansar.com/ajaxtodayshareprice"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Referer': url,
        'X-Requested-With': 'XMLHttpRequest'
    }
    try:
        logger.info("Fetching market data...")
        response = scraping_session.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            logger.error(f"Failed to fetch: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')

        for table in tables:
            try:
                table_dfs = pd.read_html(io.StringIO(str(table)))
                if not table_dfs: continue
                new_df = table_dfs[0]
                new_df = new_df.loc[:, ~new_df.columns.duplicated()]

                # Standardize columns
                symbol_col = next((c for c in new_df.columns if 'SYMBOL' in c.upper()), None)
                if symbol_col:
                    if symbol_col != 'Symbol':
                        new_df.rename(columns={symbol_col: 'Symbol'}, inplace=True)

                    # Normalize column names
                    name_mapping = {'LTP': 'LTP', 'HIGH': 'High', 'LOW': 'Low', 'OPEN': 'Open',
                                  'PREV': 'Prev. Close', 'DIFF': 'Diff', '%': 'Diff %'}
                    for col in new_df.columns:
                        for k, v in name_mapping.items():
                            if k in col.upper():
                                new_df.rename(columns={col: v}, inplace=True)
                                break
                    return new_df
            except Exception as e:
                logger.debug(f"Table parse error: {e}")

    except Exception as e:
        logger.exception(f"Scraper error: {e}")
    return None


def scrape_worker():
    """Background thread to update market data."""
    global df
    while True:
        new_data = fetch_data_from_website()
        if new_data is not None:
            with df_lock:
                df = new_data
            logger.info("Market data updated.")
        else:
            logger.warning("Data fetch failed.")

        time.sleep(60)  # Update every 60 seconds

# Start background scraper
worker_thread = threading.Thread(target=scrape_worker, daemon=True)
worker_thread.start()


# Helper functions
def get_current_user():
    return User.query.first()


def process_settlements(user):
    """Process pending T+2 settlements."""
    today = datetime.date.today()

    # Find pending settlements due today or earlier
    pending = PendingSettlement.query.filter_by(
        user_id=user.id, status='PENDING'
    ).filter(PendingSettlement.settle_date <= today).all()

    for p in pending:
        # Update holding's settled_qty
        holding = Holding.query.filter_by(user_id=user.id, symbol=p.symbol).first()
        if holding:
            holding.settled_qty += p.qty

        p.status = 'SETTLED'

    db.session.commit()


def get_market_price(symbol):
    """Get current price for a symbol."""
    with df_lock:
        if df.empty:
            return None
        row = df[df['Symbol'] == symbol]
        if not row.empty:
            try:
                return float(str(row.iloc[0]['LTP']).replace(',', '').strip())
            except:
                return None
    return None


def get_prev_close(symbol):
    """Get previous close price."""
    with df_lock:
        if df.empty:
            return None
        row = df[df['Symbol'] == symbol]
        if not row.empty:
            try:
                return float(str(row.iloc[0]['Prev. Close']).replace(',', '').strip())
            except:
                return None
    return None


@app.context_processor
def inject_user_stats():
    """Inject global stats into all templates."""
    user = get_current_user()
    if not user:
        return {}

    # Process any pending settlements
    process_settlements(user)

    # Calculate current equity
    total_investment = 0
    current_equity = 0

    market_prices = {}
    with df_lock:
        if not df.empty:
            for holding in user.holdings:
                total_investment += holding.total_cost_basis

                try:
                    row = df[df['Symbol'] == holding.symbol]
                    if not row.empty:
                        ltp = float(str(row.iloc[0]['LTP']).replace(',', '').strip())
                        market_prices[holding.symbol] = ltp
                        current_equity += ltp * holding.total_qty
                except:
                    pass

    net_worth = user.virtual_cash + current_equity
    day_gain = current_equity - total_investment
    day_gain_pct = (day_gain / total_investment * 100) if total_investment > 0 else 0

    return {
        'global_user': user,
        'global_net_worth': net_worth,
        'global_day_gain': day_gain,
        'global_day_gain_pct': day_gain_pct,
        'market_prices': market_prices
    }


# Routes
@app.route('/')
def index():
    user = get_current_user()
    process_settlements(user)

    # Get portfolio data
    holdings_data = []
    market_prices = {}

    with df_lock:
        if not df.empty:
            for holding in user.holdings:
                try:
                    row = df[df['Symbol'] == holding.symbol]
                    if not row.empty:
                        ltp = float(str(row.iloc[0]['LTP']).replace(',', '').strip())
                        prev = float(str(row.iloc[0]['Prev. Close']).replace(',', '').strip())
                        diff_pct = ((ltp - prev) / prev * 100) if prev > 0 else 0
                        market_prices[holding.symbol] = ltp

                        unrealized_pl = (ltp * holding.total_qty) - holding.total_cost_basis

                        holdings_data.append({
                            'symbol': holding.symbol,
                            'total_qty': holding.total_qty,
                            'settled_qty': holding.settled_qty,
                            'pending_qty': holding.total_qty - holding.settled_qty,
                            'wacc': holding.wacc,
                            'cost_basis': holding.total_cost_basis,
                            'ltp': ltp,
                            'current_value': ltp * holding.total_qty,
                            'unrealized_pl': unrealized_pl,
                            'unrealized_pl_pct': (unrealized_pl / holding.total_cost_basis * 100) if holding.total_cost_basis > 0 else 0,
                            'diff_pct': diff_pct,
                            'is_odd_lot': holding.total_qty % 10 != 0
                        })
                except Exception as e:
                    logger.error(f"Error processing {holding.symbol}: {e}")

    # Get pending settlements
    pending_settlements = [p.to_dict() for p in PendingSettlement.query.filter_by(
        user_id=user.id, status='PENDING').order_by(PendingSettlement.settle_date).all()]

    # Calculate totals
    total_equity = sum(h['current_value'] for h in holdings_data)
    total_investment = sum(h['cost_basis'] for h in holdings_data)
    total_unrealized_pl = sum(h['unrealized_pl'] for h in holdings_data)
    total_portfolio_value = user.virtual_cash + total_equity

    # Top movers
    top_gainers = []
    top_losers = []
    with df_lock:
        if not df.empty:
            temp_df = df.loc[:, ~df.columns.duplicated()].copy()
            # Clean Diff % column - remove % and commas, convert to numeric
            temp_df['Diff %'] = pd.to_numeric(
                temp_df['Diff %'].astype(str).str.replace('%', '').str.replace(',', ''),
                errors='coerce'
            )
            top_gainers = temp_df.nlargest(5, 'Diff %').to_dict('records')
            top_losers = temp_df.nsmallest(5, 'Diff %').to_dict('records')

    return render_template('index.html',
                          user=user,
                          holdings=holdings_data,
                          pending_settlements=pending_settlements,
                          total_equity=total_equity,
                          total_investment=total_investment,
                          total_unrealized_pl=total_unrealized_pl,
                          total_portfolio_value=total_portfolio_value,
                          top_gainers=top_gainers,
                          top_losers=top_losers)


@app.route('/marketmgmt/')
def market_index():
    """Market explorer with all stocks."""
    user = get_current_user()
    table_dict = []
    watchlist_symbols = []

    with df_lock:
        if not df.empty:
            table_dict = df.loc[:, ~df.columns.duplicated()].to_dict('records')

    watchlist_symbols = [item.symbol for item in Watchlist.query.filter_by(user_id=user.id).all()]

    return render_template('marketmgmt/index.html',
                          table_data=table_dict,
                          user=user,
                          watchlist_symbols=watchlist_symbols)


@app.route('/ordermgmt/')
def order_index():
    """Trading terminal - Buy/Sell."""
    user = get_current_user()

    recent_transactions = Transaction.query.filter_by(
        user_id=user.id
    ).order_by(Transaction.timestamp.desc()).limit(5).all()

    table_dict = []
    with df_lock:
        if not df.empty:
            table_dict = df.loc[:, ~df.columns.duplicated()].to_dict('records')

    return render_template('ordermgmt/index.html',
                          table_data=table_dict,
                          user=user,
                          recent_transactions=recent_transactions)


@app.route('/ordermgmt/history')
def order_history():
    """Full transaction history."""
    user = get_current_user()
    transactions = Transaction.query.filter_by(
        user_id=user.id
    ).order_by(Transaction.timestamp.desc()).all()

    return render_template('ordermgmt/history.html',
                          user=user,
                          transactions=transactions)


@app.route('/ordermgmt/orders')
def order_book():
    """Open orders view."""
    user = get_current_user()
    orders = Order.query.filter_by(user_id=user.id, status='OPEN').order_by(Order.created_at.desc()).all()

    return render_template('ordermgmt/orders.html',
                          user=user,
                          orders=orders)


# API Endpoints
@app.route('/api/market_data')
def api_market_data():
    """Get market data for order entry."""
    with df_lock:
        if df.empty:
            return jsonify({'symbols': [], 'data': {}})

        # Deduplicate columns first
        clean_df = df.loc[:, ~df.columns.duplicated()].copy()
        symbols = clean_df["Symbol"].tolist()
        data = {}

        for _, row in clean_df.iterrows():
            try:
                symbol = row['Symbol']
                ltp = float(str(row['LTP']).replace(',', '').strip())
                prev = float(str(row['Prev. Close']).replace(',', '').strip())
                high = float(str(row.get('High', prev)).replace(',', '').strip())
                low = float(str(row.get('Low', prev)).replace(',', '').strip())

                upper, lower = NepseTradingEngine.calculate_price_band(prev)

                data[symbol] = {
                    'ltp': ltp,
                    'prev_close': prev,
                    'high': high,
                    'low': low,
                    'upper_circuit': upper,
                    'lower_circuit': lower
                }
            except:
                pass

    return jsonify({'symbols': symbols, 'data': data})


@app.route('/api/calculate/buy', methods=['POST'])
def api_calculate_buy():
    """Calculate buy order fees."""
    data = request.json
    price = float(data.get('price', 0))
    qty = int(data.get('quantity', 0))
    symbol = data.get('symbol', '')

    if price <= 0 or qty <= 0:
        return jsonify({'success': False, 'message': 'Invalid price or quantity'})

    fees = NepseTradingEngine.calculate_fees(qty, price, 'BUY')
    slab_info = NepseTradingEngine.get_slab_info(fees['gross'])

    # Calculate new WACC if user has existing holding
    user = get_current_user()
    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()

    new_wacc = None
    if holding:
        old_cost = holding.total_cost_basis
        new_cost = fees['total_paid']
        new_qty = holding.total_qty + qty
        new_wacc = round((old_cost + new_cost) / new_qty, 2)

    # Break-even price
    break_even = None
    if new_wacc:
        break_even = NepseTradingEngine.calculate_break_even(new_wacc, qty, user.investor_type)

    return jsonify({
        'success': True,
        'fees': fees,
        'slab': slab_info,
        'new_wacc': new_wacc,
        'break_even': break_even
    })


@app.route('/api/calculate/sell', methods=['POST'])
def api_calculate_sell():
    """Calculate sell order proceeds and CGT."""
    data = request.json
    price = float(data.get('price', 0))
    qty = int(data.get('quantity', 0))
    symbol = data.get('symbol', '')

    if price <= 0 or qty <= 0:
        return jsonify({'success': False, 'message': 'Invalid price or quantity'})

    user = get_current_user()
    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()

    if not holding:
        return jsonify({'success': False, 'message': 'You do not own this stock'})

    if qty > holding.settled_qty:
        return jsonify({
            'success': False,
            'message': f'Can only sell {holding.settled_qty} shares. {holding.total_qty - holding.settled_qty} pending settlement.'
        })

    # Calculate sell proceeds
    fees = NepseTradingEngine.calculate_fees(qty, price, 'SELL')
    slab_info = NepseTradingEngine.get_slab_info(fees['gross'])

    # Calculate CGT
    cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
        qty, price, holding.wacc,
        holding.purchase_date, datetime.date.today(),
        user.investor_type
    )

    return jsonify({
        'success': True,
        'fees': fees,
        'slab': slab_info,
        'cgt': cgt_info
    })


@app.route('/api/execute/buy', methods=['POST'])
def api_execute_buy():
    """Execute buy order."""
    data = request.json
    symbol = data.get('symbol', '').upper()
    price = float(data.get('price', 0))
    qty = int(data.get('quantity', 0))

    if not symbol or price <= 0 or qty <= 0:
        return jsonify({'success': False, 'message': 'Invalid order parameters'})

    user = get_current_user()

    # Get prev close for validation
    prev_close = get_prev_close(symbol)
    if not prev_close:
        return jsonify({'success': False, 'message': 'Cannot get previous close price'})

    # Validate price band
    is_valid, msg = NepseTradingEngine.validate_price(price, prev_close)
    if not is_valid:
        return jsonify({'success': False, 'message': msg})

    # Check market hours
    is_open, msg, phase = NepseTradingEngine.is_market_open()
    if not is_open:
        return jsonify({'success': False, 'message': msg})

    # Calculate costs
    fees = NepseTradingEngine.calculate_fees(qty, price, 'BUY')
    total_required = fees['total_paid']

    if user.virtual_cash < total_required:
        return jsonify({
            'success': False,
            'message': f"Insufficient funds. Required: Rs.{total_required:,.2f}, Available: Rs.{user.virtual_cash:,.2f}"
        })

    # Execute buy
    trade_date = datetime.datetime.now()
    settle_date = NepseTradingEngine.calculate_settle_date(trade_date.date())

    # Deduct cash
    user.virtual_cash -= total_required

    # Update or create holding
    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()

    if holding:
        # Recalculate WACC
        old_qty = holding.total_qty
        old_cost = holding.total_cost_basis
        new_cost = fees['total_paid']

        new_qty = old_qty + qty
        new_wacc = (old_cost + new_cost) / new_qty
        new_cost_basis = old_cost + new_cost

        holding.total_qty = new_qty
        holding.wacc = round(new_wacc, 2)
        holding.total_cost_basis = round(new_cost_basis, 2)
        # settled_qty stays same until T+2
    else:
        holding = Holding(
            user_id=user.id,
            symbol=symbol,
            total_qty=qty,
            settled_qty=0,
            wacc=round(fees['total_paid'] / qty, 2),
            total_cost_basis=round(fees['total_paid'], 2),
            purchase_date=trade_date.date()
        )
        db.session.add(holding)

    # Create pending settlement
    pending = PendingSettlement(
        user_id=user.id,
        symbol=symbol,
        qty=qty,
        trade_date=trade_date.date(),
        settle_date=settle_date,
        status='PENDING'
    )
    db.session.add(pending)

    # Record transaction
    txn = Transaction(
        user_id=user.id,
        symbol=symbol,
        type='BUY',
        qty=qty,
        price=price,
        gross=fees['gross'],
        commission=fees['commission'],
        sebon_fee=fees['sebon'],
        dp_fee=fees['dp'],
        total_fees=fees['total_fees'],
        total_paid=fees['total_paid'],
        wacc=holding.wacc if holding else 0,
        trade_date=trade_date.date(),
        settle_date=settle_date
    )
    db.session.add(txn)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Bought {qty} shares of {symbol} @ Rs.{price}",
        'trade': txn.to_dict()
    })


@app.route('/api/execute/sell', methods=['POST'])
def api_execute_sell():
    """Execute sell order."""
    data = request.json
    symbol = data.get('symbol', '').upper()
    price = float(data.get('price', 0))
    qty = int(data.get('quantity', 0))

    if not symbol or price <= 0 or qty <= 0:
        return jsonify({'success': False, 'message': 'Invalid order parameters'})

    user = get_current_user()

    # Get prev close for validation
    prev_close = get_prev_close(symbol)
    if not prev_close:
        return jsonify({'success': False, 'message': 'Cannot get previous close price'})

    # Validate price band
    is_valid, msg = NepseTradingEngine.validate_price(price, prev_close)
    if not is_valid:
        return jsonify({'success': False, 'message': msg})

    # Check market hours
    is_open, msg, phase = NepseTradingEngine.is_market_open()
    if not is_open:
        return jsonify({'success': False, 'message': msg})

    # Check holdings
    holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()

    if not holding:
        return jsonify({'success': False, 'message': f"You don't own {symbol}"})

    if qty > holding.settled_qty:
        return jsonify({
            'success': False,
            'message': f"Only {holding.settled_qty} shares available to sell. {holding.total_qty - holding.settled_qty} shares settle on {holding.purchase_date + datetime.timedelta(days=2)}"
        })

    # Calculate sell proceeds with CGT
    trade_date = datetime.datetime.now()
    cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
        qty, price, holding.wacc,
        holding.purchase_date, trade_date.date(),
        user.investor_type
    )

    fees = NepseTradingEngine.calculate_fees(qty, price, 'SELL')

    # Add proceeds to cash
    user.virtual_cash += cgt_info['net_received']

    # Update holding
    new_total = holding.total_qty - qty

    if new_total == 0:
        db.session.delete(holding)
    else:
        new_settled = holding.settled_qty - qty
        # WACC stays the same per NEPSE rules
        holding.total_qty = new_total
        holding.settled_qty = max(0, new_settled)
        # Note: total_cost_basis is NOT reduced proportionally

    # Record transaction
    txn = Transaction(
        user_id=user.id,
        symbol=symbol,
        type='SELL',
        qty=qty,
        price=price,
        gross=fees['gross'],
        commission=fees['commission'],
        sebon_fee=fees['sebon'],
        dp_fee=fees['dp'],
        total_fees=fees['total_fees'],
        cgt=cgt_info['cgt'],
        net_received=cgt_info['net_received'],
        wacc=holding.wacc if new_total > 0 else 0,
        holding_days=cgt_info['holding_days'],
        trade_date=trade_date.date(),
        settle_date=trade_date.date()
    )
    db.session.add(txn)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Sold {qty} shares of {symbol} @ Rs.{price}",
        'trade': txn.to_dict()
    })


@app.route('/api/market_status')
def api_market_status():
    """Get current market status."""
    is_open, msg, phase = NepseTradingEngine.is_market_open()
    return jsonify({
        'is_open': is_open,
        'message': msg,
        'phase': phase
    })


@app.route('/api/holdings')
def api_holdings():
    """Get user's holdings with current prices."""
    user = get_current_user()
    holdings = []

    with df_lock:
        for h in user.holdings:
            ltp = 0
            try:
                row = df[df['Symbol'] == h.symbol]
                if not row.empty:
                    ltp = float(str(row.iloc[0]['LTP']).replace(',', '').strip())
            except:
                pass

            holdings.append({
                'symbol': h.symbol,
                'total_qty': h.total_qty,
                'settled_qty': h.settled_qty,
                'pending_qty': h.total_qty - h.settled_qty,
                'wacc': h.wacc,
                'ltp': ltp,
                'current_value': ltp * h.total_qty,
                'is_odd_lot': h.total_qty % 10 != 0
            })

    return jsonify({'holdings': holdings})


# Watchlist endpoints
@app.route('/api/watchlist')
def api_watchlist():
    """Get watchlist."""
    user = get_current_user()
    watchlist = []

    with df_lock:
        for w in Watchlist.query.filter_by(user_id=user.id).all():
            try:
                row = df[df['Symbol'] == w.symbol]
                if not row.empty:
                    ltp = float(str(row.iloc[0]['LTP']).replace(',', '').strip())
                    diff = float(str(row.iloc[0]['Diff']).replace(',', '').strip())
                    diff_pct = float(str(row.iloc[0]['Diff %']).replace('%', '').replace(',', '').strip())

                    watchlist.append({
                        'symbol': w.symbol,
                        'ltp': ltp,
                        'diff': diff,
                        'diff_pct': diff_pct
                    })
            except:
                pass

    return jsonify({'watchlist': watchlist})


@app.route('/api/watchlist/<symbol>', methods=['POST'])
def api_toggle_watchlist(symbol):
    """Add or remove from watchlist."""
    user = get_current_user()

    existing = Watchlist.query.filter_by(user_id=user.id, symbol=symbol).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'success': True, 'action': 'removed', 'symbol': symbol})
    else:
        new_watch = Watchlist(user_id=user.id, symbol=symbol)
        db.session.add(new_watch)
        db.session.commit()
        return jsonify({'success': True, 'action': 'added', 'symbol': symbol})


# Order management endpoints
@app.route('/api/orders', methods=['GET'])
def api_get_orders():
    """Get open orders."""
    user = get_current_user()
    orders = [o.to_dict() for o in Order.query.filter_by(user_id=user.id, status='OPEN').all()]
    return jsonify({'orders': orders})


@app.route('/api/orders/<int:order_id>', methods=['DELETE'])
def api_cancel_order(order_id):
    """Cancel an order."""
    user = get_current_user()
    order = Order.query.filter_by(id=order_id, user_id=user.id, status='OPEN').first()

    if not order:
        return jsonify({'success': False, 'message': 'Order not found or not open'})

    order.status = 'CANCELLED'
    db.session.commit()

    return jsonify({'success': True, 'message': f'Order {order_id} cancelled'})


# Calculator endpoint
@app.route('/api/calculator')
def api_calculator():
    """Break-even calculator."""
    symbol = request.args.get('symbol', '').upper()
    qty = int(request.args.get('qty', 0))
    buy_price = float(request.args.get('buy_price', 0))
    sell_price = float(request.args.get('sell_price', 0))

    if not symbol or qty <= 0 or buy_price <= 0:
        return jsonify({'success': False, 'message': 'Invalid parameters'})

    user = get_current_user()

    # Calculate buy fees
    buy_fees = NepseTradingEngine.calculate_fees(qty, buy_price, 'BUY')
    total_cost = buy_fees['total_paid']

    # WACC
    wacc = round(total_cost / qty, 2)

    # Break-even
    break_even = NepseTradingEngine.calculate_break_even(wacc, qty, user.investor_type)

    # If sell price provided, calculate returns
    sell_info = {}
    if sell_price > 0:
        sell_fees = NepseTradingEngine.calculate_fees(qty, sell_price, 'SELL')
        cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
            qty, sell_price, wacc,
            datetime.date.today() - datetime.timedelta(days=200),  # Assume 200 days held
            datetime.date.today(),
            user.investor_type
        )

        sell_info = {
            'sell_gross': sell_fees['gross'],
            'sell_fees': sell_fees['total_fees'],
            'cgt': cgt_info['cgt'],
            'net_received': cgt_info['net_received'],
            'profit': cgt_info['net_received'] - total_cost,
            'profit_pct': ((cgt_info['net_received'] - total_cost) / total_cost * 100) if total_cost > 0 else 0
        }

    return jsonify({
        'success': True,
        'wacc': wacc,
        'total_cost': total_cost,
        'break_even': break_even,
        'buy_fees': buy_fees,
        'sell_info': sell_info
    })


# Market index chart data
@app.route('/api/market_index')
def api_market_index():
    """Simulated NEPSE index intraday data."""
    import random
    base_val = 2605.63
    points = []
    now = datetime.datetime.now()
    start_time = now.replace(hour=11, minute=0, second=0, microsecond=0)

    curr_val = base_val
    for i in range(100):
        curr_val += random.uniform(-2, 2.5)
        points.append({
            'time': (start_time + datetime.timedelta(minutes=i*3)).strftime('%H:%M'),
            'value': round(curr_val, 2)
        })
    return jsonify({'success': True, 'data': points})


if __name__ == '__main__':
    logger.info("Starting NEPSE Virtual Trading...")
    app.run(host='0.0.0.0', port=5000, debug=True)