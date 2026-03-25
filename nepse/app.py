import os
from flask import Flask, jsonify, render_template, request, flash, redirect, url_for
import requests
import pandas as pd
from bs4 import BeautifulSoup
import io
import threading
import time
import logging
from datetime import datetime
from models import db, User, Holding, Transaction
from trading_engine import NepseTradingEngine

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nepse_sim.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-secret-key'

db.init_app(app)

with app.app_context():
    db.create_all()
    # Create default user if not exists
    if not User.query.first():
        default_user = User(username='default_user', balance=100000.0)
        db.session.add(default_user)
        db.session.commit()

# Global DataFrame to store the scraped data
df = pd.DataFrame()
df_lock = threading.Lock()

# Global session for persistent connections and cookies
scraping_session = requests.Session()

def fetch_data_from_website():
    url = "https://www.sharesansar.com/today-share-price"
    ajax_url = "https://www.sharesansar.com/ajaxtodayshareprice"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Referer': url,
        'X-Requested-With': 'XMLHttpRequest'
    }
    try:
        # 1. Get main page to extract cookies and CSRF token
        logger.info("Fetching main page for CSRF token...")
        response = scraping_session.get(url, headers=headers, timeout=15)
        logger.info(f"Main page status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch session. Status: {response.status_code}")
            return None
            
        logger.debug(f"Main page snippet: {response.text[:200]}")
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = []
        token = None
        # Check meta tag or hidden input
        token_meta = soup.find('meta', {'name': 'csrf-token'})
        if token_meta:
            token = token_meta.get('content')
        if not token:
            token_input = soup.find('input', {'name': '_token'})
            if token_input:
                token = token_input.get('value')
                
        if not token:
            logger.warning("CSRF token not found in main page snippet. Falling back to main page tables.")
            tables = soup.find_all('table')
        else:
            # 2. Fetch data via AJAX POST
            logger.info(f"Fetching AJAX data with token: {token[:10]}...")
            today = datetime.now().strftime("%Y-%m-%d")
            payload = {
                '_token': token,
                'sector': 'all_sec'
            }
            ajax_headers = headers.copy()
            ajax_headers['Content-Type'] = 'application/x-www-form-urlencoded'
            
            response = scraping_session.post(ajax_url, data=payload, headers=ajax_headers, timeout=15)
            logger.info(f"AJAX response status: {response.status_code}")
            
            if response.status_code == 200:
                ajax_soup = BeautifulSoup(response.text, 'html.parser')
                tables = ajax_soup.find_all('table')
                if not tables:
                    # If no <table> tag, maybe it's just the rows. Wrap it.
                    logger.debug("AJAX returned no table tag, wrapping in dummy table.")
                    ajax_soup = BeautifulSoup(f"<table>{response.text}</table>", 'html.parser')
                    tables = ajax_soup.find_all('table')
            else:
                logger.error(f"AJAX request failed. Status: {response.status_code}. Falling back to main page tables.")
                tables = soup.find_all('table')

        # 3. Parse tables (either from main page or AJAX)
        logger.info(f"Processing {len(tables)} tables...")
        for i, table in enumerate(tables):
            try:
                table_dfs = pd.read_html(io.StringIO(str(table)))
                if not table_dfs: continue
                new_df = table_dfs[0]
                # Deduplicate columns if any
                new_df = new_df.loc[:, ~new_df.columns.duplicated()]
                
                # Select and rename columns to standardize
                cols = []
                count = {}
                for col in new_df.columns:
                    col_name = str(col).strip()
                    if col_name in count:
                        count[col_name] += 1
                        cols.append(f"{col_name}_{count[col_name]}")
                    else:
                        count[col_name] = 0
                        cols.append(col_name)
                new_df.columns = cols
                
                # Check for symbol column
                symbol_col = next((c for c in new_df.columns if 'SYMBOL' in c.upper()), None)
                if symbol_col:
                    logger.info(f"Successfully found data in table {i}")
                    if symbol_col != 'Symbol':
                        new_df.rename(columns={symbol_col: 'Symbol'}, inplace=True)
                    
                    # Normalize columns
                    name_mapping = {'LTP':'LTP','HIGH':'High','LOW':'Low','OPEN':'Open','PREV':'Prev. Close','DIFF':'Diff','%':'Diff %'}
                    for col in new_df.columns:
                        for k, v in name_mapping.items():
                            if k in col.upper():
                                new_df.rename(columns={col: v}, inplace=True)
                                break
                    return new_df
            except Exception as e:
                logger.debug(f"Table {i} parsing error: {e}")
                
        logger.warning("No suitable market data table found in detected tables.")
    except Exception as e:
        logger.exception(f"Scraper error: {e}")
    return None

def scrape_worker():
    global df
    while True:
        logger.info("Starting scheduled data scrape...")
        new_data = fetch_data_from_website()
        if new_data is not None:
            with df_lock:
                df = new_data
            logger.info("Successfully updated market data.")
        else:
            logger.warning("Scrape failed, using existing data.")
        
        time.sleep(30)  # Wait for 30 seconds before next update

# Start background thread
worker_thread = threading.Thread(target=scrape_worker, daemon=True)
worker_thread.start()

@app.route('/')
def index():
    user = User.query.first()
    with df_lock:
        table_data = df.copy()
    
    # Strictly deduplicate for calculation
    df_calc = table_data.loc[:, ~table_data.columns.duplicated()].copy()
    
    # Required data structures for template
    portfolio = {}
    market_prices = {}
    total_investment = 0.0
    current_portfolio_value = user.balance
    day_gain = 0.0
    
    for holding in user.holdings:
        # 1. Total Investment (Cost Basis)
        total_investment += holding.wacc * holding.quantity
        
        # 2. Add to portfolio dict
        portfolio[holding.symbol] = {
            'quantity': holding.quantity,
            'avg_price': holding.wacc
        }
        
        # 3. Market Price & Current Value
        current_price = 0.0
        current_price_row = df_calc[df_calc['Symbol'] == holding.symbol]
        if not current_price_row.empty:
            try:
                val = current_price_row.iloc[0]['LTP']
                ltp_str = str(val).replace(',', '').strip()
                if ltp_str and ltp_str != 'nan':
                    current_price = float(ltp_str)
            except Exception as e:
                logger.error(f"Error parsing LTP for {holding.symbol}: {e}")
        
        market_prices[holding.symbol] = current_price
        current_portfolio_value += current_price * holding.quantity
        day_gain += (current_price - holding.wacc) * holding.quantity

    portfolio_change_pct = 0.0
    if total_investment > 0:
        portfolio_change_pct = (day_gain / total_investment) * 100

    # Convert market table to list of dicts for the footer table if needed
    # Note: index.html currently uses its own portfolio loop at the top, 
    # but might still use table_data for a "Market Watch" section if added later.
    table_dict = df_calc.to_dict('records')
    
    return render_template('index.html', 
                          user=user,
                          portfolio=portfolio,
                          market_prices=market_prices,
                          total_portfolio_value=current_portfolio_value,
                          total_investment=total_investment,
                          portfolio_change=day_gain,
                          portfolio_change_pct=portfolio_change_pct,
                          table_data=table_dict)

@app.route('/marketmgmt/')
def market_index():
    user = User.query.first()
    with df_lock:
        if df.empty:
            table_dict = []
        else:
            table_dict = df.loc[:, ~df.columns.duplicated()].to_dict('records')
    return render_template('marketmgmt/index.html', table_data=table_dict, user=user)

@app.route('/ordermgmt/')
def order_index():
    user = User.query.first()
    recent_transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.timestamp.desc()).limit(5).all()
    with df_lock:
        if df.empty:
            table_dict = []
        else:
            table_dict = df.loc[:, ~df.columns.duplicated()].to_dict('records')
    return render_template('ordermgmt/index.html', table_data=table_dict, user=user, recent_transactions=recent_transactions)

@app.route('/ordermgmt/data')
def order_data():
    with df_lock:
        if df.empty:
            return jsonify([])
        symbols = df["Symbol"].tolist()
    return jsonify(symbols)

@app.route('/ordermgmt/data2')
def order_calc():
    with df_lock:
        if df.empty:
            return jsonify({"symbols": [], "ltps": []})
        data = {
            "symbols": df["Symbol"].tolist(),
            "ltps": df["LTP"].tolist()
        }
    return jsonify(data)

@app.route('/ordermgmt/data3')
def order_sinfo():
    with df_lock:
        if df.empty:
            return jsonify({"symbols": [], "ltps": [], "lows": [], "highs": [], "pcloses": []})
        
        # Ensure we have scalars by taking the first if duplicated (shouldn't happen with dedupe above but safe)
        def get_list(col_name):
            col = df[col_name]
            if isinstance(col, pd.DataFrame):
                col = col.iloc[:, 0]
            return col.tolist()

        data = {
            "symbols": get_list("Symbol"),
            "ltps": get_list("LTP"),
            "lows": get_list("Low"),
            "highs": get_list("High"),
            "pcloses": get_list("Prev. Close")
        }
    return jsonify(data)

@app.route('/trade/execute', methods=['POST'])
def execute_trade():
    """Executes a buy or sell trade following NEPSE rules."""
    data = request.json
    symbol = data.get('symbol')
    price = float(data.get('price'))
    quantity = int(data.get('quantity'))
    trade_type = data.get('type')  # 'BUY' or 'SELL'
    
    user = User.query.first()
    
    # Check market hours
    is_open, message = NepseTradingEngine.is_market_open()
    if not is_open:
        return jsonify({"success": False, "message": message}), 400

    if trade_type == 'BUY':
        costs = NepseTradingEngine.calculate_buy_costs(price, quantity)
        if user.balance < costs['total_cost']:
            return jsonify({"success": False, "message": f"Insufficient Balance. Required: {costs['total_cost']}"}), 400
        
        user.balance -= costs['total_cost']
        
        # Update holdings
        holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
        if holding:
            # Update WACC
            total_cost_basis = (holding.wacc * holding.quantity) + costs['total_cost']
            holding.quantity += quantity
            holding.wacc = total_cost_basis / holding.quantity
        else:
            holding = Holding(user_id=user.id, symbol=symbol, quantity=quantity, wacc=costs['total_cost']/quantity)
            db.session.add(holding)
            
        txn = Transaction(user_id=user.id, symbol=symbol, type='BUY', quantity=quantity, 
                          price=price, commission=costs['commission'], sebon_fee=costs['sebon_fee'], 
                          dp_fee=costs['dp_fee'], total_amount=costs['total_cost'])
        db.session.add(txn)
        
    elif trade_type == 'SELL':
        holding = Holding.query.filter_by(user_id=user.id, symbol=symbol).first()
        if not holding or holding.quantity < quantity:
            return jsonify({"success": False, "message": "Insufficient Quantity."}), 400
        
        days_held = (datetime.utcnow() - holding.purchase_date).days
        costs = NepseTradingEngine.calculate_sell_costs(price, quantity, holding.wacc, days_held)
        
        user.balance += costs['net_receivable']
        holding.quantity -= quantity
        if holding.quantity == 0:
            db.session.delete(holding)
            
        txn = Transaction(user_id=user.id, symbol=symbol, type='SELL', quantity=quantity, 
                          price=price, commission=costs['commission'], sebon_fee=costs['sebon_fee'], 
                          dp_fee=costs['dp_fee'], cgt=costs['cgt'], total_amount=costs['net_receivable'])
        db.session.add(txn)

    db.session.commit()
    return jsonify({"success": True, "message": f"Successfully {trade_type}ed {quantity} shares of {symbol}."})

if __name__ == '__main__':
    logger.info("Starting NEPSE Virtual app...")
    app.run(host='0.0.0.0', port=5000, debug=True)