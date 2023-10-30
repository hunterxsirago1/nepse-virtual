from flask import Flask, jsonify, render_template, request
import requests
import pandas as pd
from bs4 import BeautifulSoup



import locale

url = "https://www.sharesansar.com/live-trading"
r = requests.get(url)
soup = BeautifulSoup(r.text, "html.parser")
table = soup.find("table", id="headFixed")
if table is None:
    # Handle the case when the table is not found
    print("Table element not found.")

headers = table.find_all("th")
titles = []
index = 0
for i in headers:
    title = i.text
    titles.append(title)
df = pd.DataFrame(columns=titles)
rows = table.find_all("tr")
for i in rows[1:]:
    data = i.find_all("td")
    row = [tr.text.rstrip() for tr in data]  # Use .rstrip() to remove trailing whitespaces (including \n)

    l = len(df)
    df.loc[l] = row

# Use str.replace() to remove \n from the DataFrame
df = df.replace('\n', '', regex=True)

print(df)