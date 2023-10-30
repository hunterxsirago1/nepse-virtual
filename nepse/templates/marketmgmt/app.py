from flask import Flask, render_template
import requests
import pandas as pd
from bs4 import BeautifulSoup

app = Flask(__name__)

def fetch_table_data():
    url = "https://merolagani.com/LatestMarket.aspx#0"
    r = requests.get(url)

    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table", class_="table table-hover live-trading sortable")
    headers = table.find_all("th")

    titles = []
    index = 0
    for i in headers:
        title = i.text
        titles.append(title)
        index += 1
        if index == 7:
            break

    df = pd.DataFrame(columns=titles)
    rows = table.find_all("tr")

    for i in rows[1:]:
        data = i.find_all("td")
        row = [tr.text for tr in data]
        row = list(filter(None, row))
        l = len(df)
        df.loc[l] = row

    return df

@app.route('/')
def index():
    df = fetch_table_data()
    table_html = df.to_html(index=False)
    return render_template('index.html', table=table_html)

if __name__ == '__main__':
    app.run(debug=True)
