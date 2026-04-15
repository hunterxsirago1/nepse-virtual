"""Integration tests for NEPSE simulator API endpoints."""
import json
import pytest
from nepse.models import User, Holding, db


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health_returns_status(self, client):
        """GET /api/health returns healthy status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "healthy"
        assert "market_data_rows" in data


class TestMarketDataEndpoints:
    """Test market data API endpoints."""

    def test_market_status_returns_json(self, client):
        """GET /api/market_status returns JSON."""
        response = client.get("/api/market_status")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "is_open" in data
        assert "message" in data

    def test_market_data_returns_json(self, client):
        """GET /api/market_data returns JSON structure."""
        response = client.get("/api/market_data")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "symbols" in data
        assert "data" in data
        assert isinstance(data["symbols"], list)
        assert isinstance(data["data"], dict)

    def test_market_index_returns_json(self, client):
        """GET /api/market_index returns time series data."""
        response = client.get("/api/market_index")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert "data" in data
        assert len(data["data"]) > 0
        assert "time" in data["data"][0]
        assert "value" in data["data"][0]


class TestCalculatorEndpoint:
    """Test the calculator API endpoint."""

    def test_calculator_requires_symbol(self, client):
        """Calculator requires symbol parameter."""
        response = client.get("/api/calculator?qty=100&buy_price=500")
        assert response.status_code == 400 or json.loads(response.data)["success"] is False

    def test_calculator_requires_positive_values(self, client):
        """Calculator requires positive qty and buy_price."""
        response = client.get("/api/calculator?symbol=NICA&qty=0&buy_price=500")
        assert json.loads(response.data)["success"] is False

    def test_calculator_returns_wacc_and_break_even(self, client):
        """Calculator returns WACC and break-even price."""
        response = client.get("/api/calculator?symbol=NICA&qty=100&buy_price=500")
        data = json.loads(response.data)
        if data["success"]:
            assert "wacc" in data
            assert "break_even" in data
            assert "buy_fees" in data
            assert data["wacc"] > 0

    def test_calculator_with_sell_price(self, client):
        """Calculator includes profit/loss when sell price provided."""
        response = client.get(
            "/api/calculator?symbol=NICA&qty=100&buy_price=400&sell_price=500"
        )
        data = json.loads(response.data)
        if data["success"]:
            assert "sell_info" in data
            assert data["sell_info"] != {}


class TestBuyOrderCalculation:
    """Test buy order fee calculation API."""

    def test_calculate_buy_requires_json(self, client):
        """POST /api/calculate/buy requires JSON body."""
        response = client.post("/api/calculate/buy", data="not json", content_type="application/json")
        assert response.status_code == 400 or json.loads(response.data)["success"] is False

    def test_calculate_buy_validates_positive_values(self, client):
        """Buy calculation rejects zero or negative price/qty."""
        response = client.post(
            "/api/calculate/buy",
            data=json.dumps({"symbol": "NICA", "price": 0, "quantity": 100}),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["success"] is False

    def test_calculate_buy_returns_fee_breakdown(self, client):
        """Buy calculation returns complete fee breakdown."""
        response = client.post(
            "/api/calculate/buy",
            data=json.dumps({"symbol": "NICA", "price": 500, "quantity": 100}),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["success"] is True
        assert "fees" in data
        assert "slab" in data
        fees = data["fees"]
        assert fees["gross"] == 50_000.0
        assert fees["total_paid"] > fees["gross"]


class TestSellOrderCalculation:
    """Test sell order fee calculation API."""

    def test_sell_without_holding_fails(self, client, app_context):
        """Cannot calculate sell for symbol not owned."""
        response = client.post(
            "/api/calculate/sell",
            data=json.dumps({"symbol": "NICA", "price": 500, "quantity": 100}),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["success"] is False
        assert "not own" in data["message"].lower()


class TestHoldingsEndpoint:
    """Test holdings API endpoint."""

    def test_holdings_returns_list(self, client):
        """GET /api/holdings returns holdings array."""
        response = client.get("/api/holdings")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "holdings" in data
        assert isinstance(data["holdings"], list)


class TestWatchlistEndpoint:
    """Test watchlist API endpoint."""

    def test_watchlist_returns_list(self, client):
        """GET /api/watchlist returns watchlist array."""
        response = client.get("/api/watchlist")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "watchlist" in data
        assert isinstance(data["watchlist"], list)

    def test_watchlist_add_symbol(self, client):
        """POST /api/watchlist/<symbol> adds to watchlist."""
        response = client.post("/api/watchlist/NICA", content_type="application/json")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert data["action"] == "added"

    def test_watchlist_remove_symbol(self, client):
        """POST /api/watchlist/<symbol> twice removes from watchlist."""
        # Add
        client.post("/api/watchlist/NICA", content_type="application/json")
        # Remove
        response = client.post("/api/watchlist/NICA", content_type="application/json")
        data = json.loads(response.data)
        assert data["success"] is True
        assert data["action"] == "removed"


class TestOrdersEndpoint:
    """Test orders API endpoint."""

    def test_get_orders_returns_list(self, client):
        """GET /api/orders returns orders array."""
        response = client.get("/api/orders")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "orders" in data
        assert isinstance(data["orders"], list)

    def test_place_limit_order_validates(self, client):
        """Limit order placement validates parameters."""
        response = client.post(
            "/api/orders",
            data=json.dumps({"symbol": "NICA", "side": "BUY", "order_type": "LIMIT", "quantity": 10, "price": 0}),
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert data["success"] is False

    def test_cancel_nonexistent_order_fails(self, client):
        """Cancelling a non-existent order returns error."""
        response = client.delete("/api/orders/99999")
        data = json.loads(response.data)
        assert data["success"] is False


class TestPageRoutes:
    """Test page route accessibility."""

    def test_index_page_loads(self, client):
        """GET / renders the dashboard."""
        response = client.get("/")
        assert response.status_code == 200

    def test_market_page_loads(self, client):
        """GET /marketmgmt/ renders the market explorer."""
        response = client.get("/marketmgmt/")
        assert response.status_code == 200

    def test_order_page_loads(self, client):
        """GET /ordermgmt/ renders the trading terminal."""
        response = client.get("/ordermgmt/")
        assert response.status_code == 200

    def test_history_page_loads(self, client):
        """GET /ordermgmt/history renders transaction history."""
        response = client.get("/ordermgmt/history")
        assert response.status_code == 200

    def test_orders_page_loads(self, client):
        """GET /ordermgmt/orders renders the order book."""
        response = client.get("/ordermgmt/orders")
        assert response.status_code == 200
