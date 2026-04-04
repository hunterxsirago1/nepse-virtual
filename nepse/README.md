# NEPSE Virtual Trading Simulator

A realistic NEPSE (Nepal Stock Exchange) paper trading simulator with accurate trading rules, T+2 settlement, and full fee breakdown.

## Features

- **T+2 Settlement**: Shares bought today can only be sold after 2 business days
- **No Intraday Trading**: Cannot sell shares bought on the same day
- **Price Band**: ±10% circuit breaker validation
- **Full Fee Breakdown**: Commission, SEBON, DP charges, CGT
- **CGT Calculation**: 7.5% (<365 days), 5% (≥365 days), 10% institutional
- **WACC**: Weighted Average Cost Capital calculation per NEPSE rules
- **Debug Mode**: Market always open for testing

## Running the App

```bash
cd nepse
python app.py
```

Open http://localhost:5000 in your browser.

## Trading Rules Implemented

1. **Market Hours**: 11:00 AM - 3:00 PM NST (Debug mode: always open)
2. **Settlement**: T+2 business days (skipping weekends/holidays)
3. **Commission Slabs**:
   - Up to Rs. 50,000: 0.36%
   - Rs. 50,001 - 500,000: 0.33%
   - Rs. 500,001 - 20,00,000: 0.306%
   - Rs. 20,00,001 - 1,00,00,000: 0.27%
   - Above Rs. 1 crore: 0.243%
4. **SEBON Fee**: 0.015% on gross (both buy/sell)
5. **DP Charge**: Rs. 25 flat per transaction
6. **CGT**: Short-term 7.5%, Long-term 5%, Institutional 10%

## Pages

- **Dashboard**: Portfolio overview, P&L, pending settlements
- **Trading Terminal**: Buy/Sell with live fee preview
- **Market Explorer**: Live market data with watchlist
- **Order History**: Full transaction log with fee breakdown

## TODO

- [ ] Fetch real market buy/sell prices (currently using scraped LTP)
- [ ] Implement limit and stop-loss orders
- [ ] Add more Nepal holidays
- [ ] User authentication
- [ ] Reset account / start fresh

## Tech Stack

- Flask + SQLAlchemy
- Pandas for data processing
- BeautifulSoup for web scraping
- Chart.js for visualizations

## Data Source

Market data is scraped from ShareSansar.com