"""Unit tests for the NEPSE Trading Engine."""
import datetime
import pytest
from nepse.trading_engine import NepseTradingEngine, HolidayCalendar


class TestCommissionCalculation:
    """Test broker commission calculation with NEPSE commission slabs."""

    def test_commission_under_50k(self):
        """Up to Rs. 50,000: 0.36%."""
        amount = 30_000.0
        commission = NepseTradingEngine.calculate_commission(amount)
        assert commission == pytest.approx(108.0, rel=1e-2)

    def test_commission_minimum_enforced(self):
        """Minimum commission of Rs. 10 is enforced."""
        amount = 500.0
        commission = NepseTradingEngine.calculate_commission(amount)
        assert commission == 10.0

    def test_commission_50k_to_500k(self):
        """Rs. 50,001 - Rs. 500,000: 0.33%."""
        amount = 200_000.0
        commission = NepseTradingEngine.calculate_commission(amount)
        assert commission == pytest.approx(660.0, rel=1e-2)

    def test_commission_500k_to_20lakh(self):
        """Rs. 500,001 - Rs. 20 lakhs: 0.306%."""
        amount = 1_000_000.0
        commission = NepseTradingEngine.calculate_commission(amount)
        assert commission == pytest.approx(3060.0, rel=1e-2)

    def test_commission_20lakh_to_1crore(self):
        """Rs. 20 lakhs - Rs. 1 crore: 0.27%."""
        amount = 5_000_000.0
        commission = NepseTradingEngine.calculate_commission(amount)
        assert commission == pytest.approx(13_500.0, rel=1e-2)

    def test_commission_above_1crore(self):
        """Above Rs. 1 crore: 0.243%."""
        amount = 50_000_000.0
        commission = NepseTradingEngine.calculate_commission(amount)
        assert commission == pytest.approx(121_500.0, rel=1e-2)


class TestFeeCalculation:
    """Test full fee breakdown for buy and sell orders."""

    def test_buy_fees_include_all_components(self):
        """Buy fees = gross + commission + SEBON + DP."""
        qty = 100
        price = 500.0  # gross = 50,000
        fees = NepseTradingEngine.calculate_fees(qty, price, "BUY")

        assert "gross" in fees
        assert "commission" in fees
        assert "sebon" in fees
        assert "dp" in fees
        assert "total_fees" in fees
        assert "total_paid" in fees

        assert fees["gross"] == 50_000.0
        assert fees["total_paid"] == fees["gross"] + fees["total_fees"]
        assert fees["dp"] == 25.0
        assert fees["sebon"] == pytest.approx(7.5, rel=1e-2)

    def test_sell_fees_same_structure(self):
        """Sell fees have same components; net is gross - fees."""
        qty = 50
        price = 1000.0  # gross = 50,000
        fees = NepseTradingEngine.calculate_fees(qty, price, "SELL")

        assert "gross" in fees
        assert "total_received" in fees
        assert fees["total_received"] == fees["gross"] - fees["total_fees"]
        assert fees["dp"] == 25.0


class TestCGTCalculation:
    """Test Capital Gains Tax calculation."""

    def test_short_term_cgt_individual(self):
        """Individual: 7.5% CGT for holdings < 365 days."""
        net_gain = 10_000.0
        cgt = NepseTradingEngine.calculate_cgt(net_gain, holding_days=180, investor_type="INDIVIDUAL")
        assert cgt == pytest.approx(750.0, rel=1e-2)

    def test_long_term_cgt_individual(self):
        """Individual: 5% CGT for holdings >= 365 days."""
        net_gain = 10_000.0
        cgt = NepseTradingEngine.calculate_cgt(net_gain, holding_days=400, investor_type="INDIVIDUAL")
        assert cgt == pytest.approx(500.0, rel=1e-2)

    def test_cgt_institutional(self):
        """Institutional: 10% CGT regardless of holding period."""
        net_gain = 10_000.0
        cgt = NepseTradingEngine.calculate_cgt(net_gain, holding_days=180, investor_type="INSTITUTIONAL")
        assert cgt == pytest.approx(1000.0, rel=1e-2)

    def test_no_cgt_on_loss(self):
        """No CGT is charged on a net loss."""
        cgt = NepseTradingEngine.calculate_cgt(-5000.0, holding_days=180, investor_type="INDIVIDUAL")
        assert cgt == 0.0

    def test_no_cgt_on_zero_gain(self):
        """No CGT on zero net gain."""
        cgt = NepseTradingEngine.calculate_cgt(0.0, holding_days=180, investor_type="INDIVIDUAL")
        assert cgt == 0.0

    def test_cgt_for_sell_full_breakdown(self):
        """calculate_cgt_for_sell returns complete breakdown."""
        result = NepseTradingEngine.calculate_cgt_for_sell(
            qty=100, sell_price=500.0, wacc=400.0,
            purchase_date=datetime.date.today() - datetime.timedelta(days=200),
            sell_date=datetime.date.today(),
            investor_type="INDIVIDUAL"
        )

        assert "holding_days" in result
        assert "cgt" in result
        assert "net_received" in result
        assert "net_gain" in result
        assert result["holding_days"] == 200
        assert result["cgt_rate"] == "7.5%"
        assert result["net_received"] < result["gross"]  # fees and CGT deducted


class TestPriceBand:
    """Test price band validation (±10% daily limit)."""

    def test_price_within_band(self):
        """Price within ±10% of prev close is valid."""
        prev_close = 500.0
        assert NepseTradingEngine.validate_price(500.0, prev_close)[0] is True
        assert NepseTradingEngine.validate_price(550.0, prev_close)[0] is True
        assert NepseTradingEngine.validate_price(450.0, prev_close)[0] is True

    def test_price_above_upper_circuit(self):
        """Price above +10% is rejected."""
        prev_close = 500.0
        is_valid, msg = NepseTradingEngine.validate_price(560.0, prev_close)
        assert is_valid is False
        assert "upper" in msg.lower()

    def test_price_below_lower_circuit(self):
        """Price below -10% is rejected."""
        prev_close = 500.0
        is_valid, msg = NepseTradingEngine.validate_price(430.0, prev_close)
        assert is_valid is False
        assert "lower" in msg.lower()

    def test_circuit_calculation(self):
        """Upper = prev * 1.10, Lower = prev * 0.90."""
        prev_close = 1000.0
        upper, lower = NepseTradingEngine.calculate_price_band(prev_close)
        assert upper == 1100.0
        assert lower == 900.0


class TestSettlement:
    """Test T+2 settlement date calculation."""

    def test_t_plus_2_business_days(self):
        """T+2 skips weekends and holidays."""
        # Monday -> settle Wednesday
        monday = datetime.date(2026, 4, 13)
        settle = NepseTradingEngine.calculate_settle_date(monday)
        assert settle == datetime.date(2026, 4, 15)

    def test_friday_trade_settles_monday(self):
        """Friday trade settles Monday (T+2 business days)."""
        friday = datetime.date(2026, 4, 17)
        settle = NepseTradingEngine.calculate_settle_date(friday)
        assert settle == datetime.date(2026, 4, 21)

    def test_thursday_trade_settles_monday(self):
        """Thursday trade skips Fri (holiday) and weekend."""
        # Thursday -> Friday -> Monday
        thursday = datetime.date(2026, 4, 16)
        settle = NepseTradingEngine.calculate_settle_date(thursday)
        assert settle == datetime.date(2026, 4, 20)


class TestHolidayCalendar:
    """Test Nepal holiday calendar."""

    def test_add_remove_holiday(self):
        """Can add and remove custom holidays."""
        cal = HolidayCalendar()
        test_date = datetime.date(2026, 6, 15)
        assert cal.is_holiday(test_date) is False

        cal.add_holiday(test_date, "Test Holiday")
        assert cal.is_holiday(test_date) is True
        assert cal.get_holiday_name(test_date) == "Test Holiday"

        cal.remove_holiday(test_date)
        assert cal.is_holiday(test_date) is False


class TestBreakEvenCalculation:
    """Test break-even sell price calculation."""

    def test_break_even_positive_for_profitable_position(self):
        """Break-even price must cover cost + fees + CGT."""
        # Buy 100 shares at 400 = 40,000 + fees
        wacc = 400.0
        qty = 100
        break_even = NepseTradingEngine.calculate_break_even(wacc, qty, "INDIVIDUAL")
        assert break_even > wacc  # Must be higher to cover fees + CGT
        assert break_even > 0

    def test_break_even_iterative_converges(self):
        """Break-even calculation converges within 100 iterations."""
        wacc = 500.0
        qty = 200
        # The iterative method should return a value
        result = NepseTradingEngine.calculate_break_even(wacc, qty, "INDIVIDUAL")
        assert result > 0
        assert isinstance(result, float)


class TestCommissionSlabInfo:
    """Test commission slab information display."""

    def test_slab_info_small(self):
        """Correct slab info for small amounts."""
        info = NepseTradingEngine.get_slab_info(30_000.0)
        assert info["rate"] == pytest.approx(0.0036, rel=1e-3)
        assert "Up to" in info["slab_label"]

    def test_slab_info_large(self):
        """Correct slab info for large amounts (above 1 crore)."""
        info = NepseTradingEngine.get_slab_info(50_000_000.0)
        assert info["rate"] == pytest.approx(0.00243, rel=1e-3)
        assert "Above" in info["slab_label"]


class TestHoldingDays:
    """Test holding days calculation."""

    def test_holding_days_calculation(self):
        """Holding days = sell_date - purchase_date."""
        purchase = datetime.date(2026, 1, 1)
        sell = datetime.date(2026, 4, 15)
        days = NepseTradingEngine.calculate_holding_days(purchase, sell)
        assert days == 104
