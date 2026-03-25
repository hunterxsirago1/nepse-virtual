import os
from flask import Flask, jsonify, render_template, request, flash, redirect, url_for
import requests
import pandas as pd
from bs4 import BeautifulSoup
import threading
import time
import logging
from datetime import datetime
from models import db, User, Holding, Transaction
from trading_engine import NepseTradingEngine

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

def fetch_data_from_website():
    url = "https://www.sharesansar.com/live-nepse"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', {'id': 'headFixed'})
            if table:
                new_df = pd.read_html(str(table))[0]
                return new_df
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
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
    
    # Calculate portfolio value and gain/loss
    portfolio_value = 0
    day_gain = 0
    holdings_count = len(user.holdings)
    
    for holding in user.holdings:
        current_price_row = table_data[table_data['Symbol'] == holding.symbol]
        if not current_price_row.empty:
            ltp_str = str(current_price_row.iloc[0]['LTP']).replace(',', '')
            current_price = float(ltp_str)
            portfolio_value += current_price * holding.quantity
            day_gain += (current_price - holding.wacc) * holding.quantity
    
    return render_template('index.html', 
                          table_data=table_data, 
                          user=user, 
                          portfolio_value=round(portfolio_value, 2),
                          day_gain=round(day_gain, 2),
                          holdings_count=holdings_count)

@app.route('/marketmgmt/')
def market_index():
    user = User.query.first()
    with df_lock:
        table_data = df.copy()
    return render_template('marketmgmt/index.html', table_data=table_data, user=user)

@app.route('/ordermgmt/')
def order_index():
    user = User.query.first()
    with df_lock:
        table_data = df.copy()
    return render_template('ordermgmt/index.html', table_data=table_data, user=user)

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
        data = {
            "symbols": df["Symbol"].tolist(),
            "ltps": df["LTP"].tolist(),
            "lows": df["Low"].tolist(),
            "highs": df["High"].tolist(),
            "pcloses": df["Prev. Close"].tolist()
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