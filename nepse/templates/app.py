from flask import Flask, jsonify, render_template
import requests
import pandas as pd
from bs4 import BeautifulSoup

app = Flask(__name__)

def scrape_data():
    import locale

    def swap_positions(array, pos1, pos2):
        array[pos1], array[pos2] = array[pos2], array[pos1]

    url = "https://merolagani.com/LatestMarket.aspx#0"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_="table table-hover live-trading sortable")

    if table is None:
        # Handle the case when the table is not found
        print("Table element not found.")
        return None

    headers = table.find_all("th")
    titles = []
    index = 0
    for i in headers:
        title = i.text
        titles.append(title)
        index += 1
        if index == 9:
            break

    df = pd.DataFrame(columns=titles)
    rows = table.find_all("tr")

    for i in rows[1:]:
        data = i.find_all("td")
        row = [tr.text for tr in data]

        swap_positions(row, 3, 5)
        swap_positions(row, 4, 5)

        if row[2] is not None and row[1] is not None:
            element1 = float(row[1].replace(',', ''))
            element2 = float(row[2].replace(',', ''))
            new_value = float(abs(element2) * element1 / 100 + element1)

            if row[7] == '':
                row[7] = locale.format_string("%.2f", new_value, grouping=True)
            new_value1 = float(element1 - new_value)
            if row[8] == '':
                row[8] = locale.format_string("%.2f", new_value1, grouping=True)

        l = len(df)
        df.loc[l] = row

    return df

@app.route('/')
def index():
    table_data = scrape_data()
    return render_template('index.html', table_data=table_data)

@app.route('/marketmgmt/')
def market_index():
    table_data = scrape_data()
    return render_template('marketmgmt/index.html', table_data=table_data)

@app.route('/ordermgmt/')
def order_index():
    return render_template('ordermgmt/index.html')

@app.route('/ordermgmt/data')
def order_data():
    url = "https://merolagani.com/LatestMarket.aspx#0"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_="table table-hover live-trading sortable")

    if table is None:
        # Handle the case when the table is not found
        print("Table element not found.")
        return None

    headers = table.find_all("th")
    titles = []
    index = 0
    for i in headers:
        title = i.text
        titles.append(title)
        index += 1
        if index == 9:
            break

    df = pd.DataFrame(columns=titles)
    rows = table.find_all("tr")

    for i in rows[1:]:
        data = i.find_all("td")
        row = [tr.text for tr in data]
        df.loc[len(df)] = row

    symbol_column = df["Symbol"]
    return symbol_column.to_json(orient='values')

if __name__ == '__main__':
    app.run(debug=True)
