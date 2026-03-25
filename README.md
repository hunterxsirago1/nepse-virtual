# NEPSE Virtual Trading Simulator

A professional, real-time NEPSE (Nepal Stock Exchange) live trading simulator and dashboard. This application scrapes live trading data from Sharesansar and provides a virtual platform for monitoring and simulating stock trades.

## Features
- **Real-time Live Trading Dashboard**: Monitor NEPSE stocks with live updates every 30 seconds.
- **Market Management**: Comprehensive market data view with search and filter capabilities.
- **Order Management (Simulation)**: Simulate Buy/Sell orders with real-time price tracking.
- **Watchlist & Portfolio Tracking**: Keep track of your favorite stocks and simulated holdings.

## Tech Stack
- **Backend**: Flask (Python)
- **Data Processing**: Pandas, BeautifulSoup4
- **Frontend**: HTML5, Vanilla CSS3, JavaScript (ES6+)
- **Scheduler**: APScheduler for background data synchronization

## Getting Started

### Prerequisites
- Python 3.8+
- `pip` package manager

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/hunterxsirago1/nepse-virtual.git
   cd nepse-virtual
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python nepse/app.py
   ```
4. Access the dashboard:
   Open your browser and navigate to `http://127.0.0.1:5000/`

## Project Structure
- `nepse/app.py`: Main Flask application and data scraping logic.
- `nepse/static/`: Static assets (CSS, JS, Images).
- `nepse/templates/`: HTML templates for different management views.

## License
MIT License - Feel free to use and contribute!
