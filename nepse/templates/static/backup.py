from flask import Flask, jsonify, render_template, request, g
import requests
import pandas as pd
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import time

app = Flask(__name__)

# Global DataFrame to store the scraped data
df = pd.DataFrame()
df_lock = threading.Lock()

# Background scheduler for updating data
scheduler = BackgroundScheduler(daemon=True)

def fetch_data_from_website():
    url = "https://www.sharesansar.com/live-trading"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", id="headFixed")
    if table is None:
        # Handle the case when the table is not found
        print("Table element not found.")
        return None

    headers = table.find_all("th")
    titles = [i.text for i in headers]

    rows = table.find_all("tr")[1:]
    data = []
    for row in rows:
        cells = row.find_all("td")
        row_data = [cell.text.rstrip() for cell in cells]
        data.append(row_data)

    # Use str.replace() to remove \n from the DataFrame
    df = pd.DataFrame(data, columns=titles).replace('\n', '', regex=True)
    return df

def scrape_data():
    new_data = fetch_data_from_website()
    if new_data is not None:
        with df_lock:
            global df
            df = new_data

def update_data():
    while True:
        scrape_data()
        time.sleep(30)  # Wait for 30 seconds before the next update

# Start the background thread for data update
update_thread = threading.Thread(target=update_data)
update_thread.daemon = True  # Set as a daemon thread to stop when the main thread stops
update_thread.start()

@app.route('/')
def index():
    with df_lock:
        table_data = df.copy()
    return render_template('index.html', table_data=table_data)

@app.route('/marketmgmt/')
def market_index():
    with df_lock:
        table_data = df.copy()
    return render_template('marketmgmt/index.html', table_data=table_data)

@app.route('/ordermgmt/')
def order_index():
    with df_lock:
        table_data = df.copy()
    return render_template('ordermgmt/index.html', table_data=table_data)

@app.route('/ordermgmt/data')
def order_data():
    table_data = df.copy()
    symbol_column = table_data["Symbol"]
    return symbol_column.to_json(orient='values')

@app.route('/ordermgmt/data2')
def order_calc():
    table_data = df.copy()
    symbol_column = table_data["Symbol"]
    ltp_column = table_data["LTP"]
    data = {
        "symbols": symbol_column.tolist(),
        "ltps": ltp_column.tolist()
    }
    return jsonify(data)

@app.route('/ordermgmt/data3')
def order_sinfo():
    table_data = df.copy()
    symbol_column = table_data["Symbol"]
    ltp_column = table_data["LTP"]
    low_column = table_data["Low"]
    high_column = table_data["High"]
    pclose_column = table_data["Prev. Close"]

    data = {
        "symbols": symbol_column.tolist(),
        "ltps": ltp_column.tolist(),
        "lows": low_column.tolist(),
        "highs": high_column.tolist(),
        "pcloses": pclose_column.tolist()

    }
    return jsonify(data)

if __name__ == '__main__':
    # Start the Flask app
    app.run(debug=True)