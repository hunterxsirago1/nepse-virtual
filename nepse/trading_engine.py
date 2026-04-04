import datetime
import math
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass, field

@dataclass
class NepalHoliday:
    """Represents a Nepal public holiday."""
    date: datetime.date
    name: str

class HolidayCalendar:
    """Manages Nepal public holidays."""

    # Nepal public holidays for 2026 (BS 2082/83)
    # Format: (year, month, day, name)
    HOLIDAYS_2026 = [
        # Magh (Jan-Feb)
        (2026, 1, 14, "Maghe Sankranti"),
        # Falgun (Feb-Mar)
        (2026, 2, 24, "Shivaratri"),
        # Chaitra (Mar-Apr)
        (2026, 3, 9, "Holi / Phagu Purnima"),
        (2026, 3, 14, "Nepali New Year's Day"),
        # Baisakh (Apr-May)
        (2026, 4, 14, "Baisakhi"),
        # Jestha (May-Jun)
        (2026, 5, 1, "International Workers' Day"),
        (2026, 5, 14, "Buddha Jayanti"),
        # Asar (Jun-Jul)
        # No major holidays in Asar
        # Shrawan (Jul-Aug)
        (2026, 7, 9, "Kukur Tihar / Gaura Parba"),
        # Bhadra (Aug-Sep)
        (2026, 8, 19, "Krishna Janmashtami"),
        (2026, 8, 28, "Haritalika Teej"),
        # Ashwin (Sep-Oct)
        (2026, 9, 27, "Ghatasthapana"),
        (2026, 10, 4, "Maha Dashami"),
        (2026, 10, 5, "Fulpati"),
        (2026, 10, 6, "Bijaya Dashami"),
        (2026, 10, 13, "Kojagrat Purnima / Vijaya Dashami"),
        # Kartik (Oct-Nov)
        (2026, 10, 20, "Chhath"),
        (2026, 11, 2, "Sharda Tibeto-Burman New Year"),
        # Mangsir (Nov-Dec)
        (2026, 11, 9, "National Unity Day"),
        (2026, 11, 26, "Constitution Day"),
        # Poush (Dec-Jan)
        (2026, 12, 25, "Christmas Day / Tamu Lhosar"),
        # Magh (Jan-Feb)
        (2026, 12, 31, "Losar / Tamu Lhosar"),
    ]

    def __init__(self):
        self._holidays: Dict[datetime.date, str] = {}
        for y, m, d, name in self.HOLIDAYS_2026:
            self._holidays[datetime.date(y, m, d)] = name

    def add_holiday(self, date: datetime.date, name: str):
        """Add a custom holiday."""
        self._holidays[date] = name

    def remove_holiday(self, date: datetime.date):
        """Remove a holiday."""
        if date in self._holidays:
            del self._holidays[date]

    def is_holiday(self, date: datetime.date) -> bool:
        """Check if date is a Nepal public holiday."""
        return date in self._holidays

    def get_holiday_name(self, date: datetime.date) -> Optional[str]:
        """Get holiday name if date is a holiday."""
        return self._holidays.get(date)


# Global holiday calendar instance
holiday_calendar = HolidayCalendar()


class NepseTradingEngine:
    """
    NEPSE Paper Trading Engine
    Implements accurate Nepal Stock Exchange trading rules.
    """

    # Debug mode - always open for testing
    DEBUG_ALWAYS_OPEN = True

    # Commission Slabs (effective from Jestha 1, 2081 - May 14, 2024)
    # Applied to GROSS transaction amount (not progressive)
    COMMISSION_SLABS = [
        (50000, 0.0036),        # Up to 50k: 0.36%
        (500000, 0.0033),       # 50k - 500k: 0.33%
        (2000000, 0.00306),     # 500k - 20 lakhs: 0.306%
        (10000000, 0.0027),     # 20 lakhs - 1 crore: 0.27%
        (float('inf'), 0.00243) # Over 1 crore: 0.243%
    ]

    MINIMUM_COMMISSION = 10.0  # Rs. 10 minimum per transaction
    SEBON_FEE_RATE = 0.00015   # 0.015% (both buy and sell)
    DP_CHARGE = 25.0           # Rs. 25 flat per transaction (both buy and sell)

    # CGT Rates
    CGT_SHORT_TERM_RATE = 0.075  # 7.5% for holdings < 365 days
    CGT_LONG_TERM_RATE = 0.05    # 5% for holdings >= 365 days

    # Market hours (NST = UTC+5:45)
    PRE_OPEN_START = datetime.time(10, 30)  # 10:30 AM - Order entry
    PRE_OPEN_END = datetime.time(11, 0)     # 11:00 AM - Market opens
    MARKET_OPEN = datetime.time(11, 0)      # 11:00 AM
    MARKET_CLOSE = datetime.time(15, 0)      # 3:00 PM

    # Price band limits
    PRICE_BAND_PERCENT = 0.10  # ±10% from prev close

    # Order validity
    MAX_GTC_DAYS = 15          # GTC orders expire after 15 days

    @staticmethod
    def is_weekend(date: datetime.date) -> bool:
        """Check if date is Saturday (5) or Sunday (6)."""
        return date.weekday() >= 5

    @staticmethod
    def is_trading_day(date: datetime.date) -> bool:
        """
        Check if date is a valid trading day (Mon-Fri, not holiday).
        """
        # Must be weekday (Monday=0 to Friday=4)
        if date.weekday() >= 5:
            return False
        # Must not be a holiday
        return not holiday_calendar.is_holiday(date)

    @staticmethod
    def calculate_settle_date(trade_date: datetime.date) -> datetime.date:
        """
        Calculate T+2 settlement date.
        Counts 2 BUSINESS days (skip weekends and holidays).

        Args:
            trade_date: The date of the trade

        Returns:
            Settlement date (T+2 business days)
        """
        count = 0
        day = trade_date

        while count < 2:
            day += datetime.timedelta(days=1)
            # Only count if not weekend AND not holiday
            if not NepseTradingEngine.is_weekend(day) and not holiday_calendar.is_holiday(day):
                count += 1

        return day

    @staticmethod
    def calculate_settle_date_from_trade_datetime(trade_dt: datetime.datetime) -> datetime.datetime:
        """
        Calculate T+2 settlement datetime (uses trade date, not datetime).
        """
        trade_date = trade_dt.date()
        settle_date = NepseTradingEngine.calculate_settle_date(trade_date)
        return datetime.datetime.combine(settle_date, datetime.time(9, 0))

    @staticmethod
    def is_market_open() -> Tuple[bool, str, str]:
        """
        Check if market is currently open.

        Returns:
            Tuple of (is_open, message, phase)
            phase can be: CLOSED, PRE_OPEN, REGULAR
        """
        # Debug mode - always open for testing
        if NepseTradingEngine.DEBUG_ALWAYS_OPEN:
            return True, "Market is Open (Debug Mode).", "REGULAR"

        now = datetime.datetime.now()
        current_time = now.time()

        # Saturday (5) and Sunday (6) - always closed
        if now.weekday() >= 5:
            return False, "Market is Closed (Weekend).", "CLOSED"

        # Check if today is a holiday
        if holiday_calendar.is_holiday(now.date()):
            return False, f"Market is Closed ({holiday_calendar.get_holiday_name(now.date())}).", "CLOSED"

        # Pre-open session (10:30 - 11:00)
        if NepseTradingEngine.PRE_OPEN_START <= current_time < NepseTradingEngine.MARKET_OPEN:
            return True, "Market is in Pre-Open Session (10:30-11:00).", "PRE_OPEN"

        # Regular session (11:00 - 15:00)
        if NepseTradingEngine.MARKET_OPEN <= current_time <= NepseTradingEngine.MARKET_CLOSE:
            return True, "Market is Open.", "REGULAR"

        # Before or after hours
        if current_time < NepseTradingEngine.PRE_OPEN_START:
            return False, "Market opens at 10:30 AM (Pre-open).", "CLOSED"

        return False, "Market is Closed. Trading Hours: Mon-Fri, 11:00 AM - 3:00 PM.", "CLOSED"

    @staticmethod
    def is_trading_day_today() -> Tuple[bool, str]:
        """Check if today is a trading day."""
        today = datetime.datetime.now().date()
        if NepseTradingEngine.is_weekend(today):
            return False, "Today is a weekend."
        if holiday_calendar.is_holiday(today):
            return False, f"Today is a public holiday ({holiday_calendar.get_holiday_name(today)})."
        return True, "Today is a trading day."

    @staticmethod
    def calculate_commission(gross_amount: float) -> float:
        """
        Calculate broker commission based on gross amount.
        Uses flat slab rate on entire amount (not progressive).
        Minimum Rs. 10.
        """
        rate = 0.0036  # Default to highest rate
        for limit, slab_rate in NepseTradingEngine.COMMISSION_SLABS:
            if gross_amount <= limit:
                rate = slab_rate
                break

        commission = gross_amount * rate
        return max(commission, NepseTradingEngine.MINIMUM_COMMISSION)

    @staticmethod
    def calculate_fees(qty: int, price: float, side: str) -> Dict[str, float]:
        """
        Calculate all fees for a transaction.

        Args:
            qty: Number of shares
            price: Price per share
            side: 'BUY' or 'SELL'

        Returns:
            Dictionary with: gross, commission, sebon, dp, total_fees, total_paid/received
        """
        gross = float(qty * price)
        commission = NepseTradingEngine.calculate_commission(gross)
        sebon = gross * NepseTradingEngine.SEBON_FEE_RATE
        dp = NepseTradingEngine.DP_CHARGE

        total_fees = commission + sebon + dp

        if side.upper() == 'BUY':
            return {
                'gross': round(gross, 2),
                'commission': round(commission, 2),
                'sebon': round(sebon, 2),
                'dp': round(dp, 2),
                'total_fees': round(total_fees, 2),
                'total_paid': round(gross + total_fees, 2)
            }
        else:
            return {
                'gross': round(gross, 2),
                'commission': round(commission, 2),
                'sebon': round(sebon, 2),
                'dp': round(dp, 2),
                'total_fees': round(total_fees, 2),
                'total_received': round(gross - total_fees, 2)
            }

    @staticmethod
    def calculate_cgt(net_gain: float, holding_days: int, investor_type: str = "INDIVIDUAL") -> float:
        """
        Calculate Capital Gains Tax.

        Args:
            net_gain: Profit from sale (after fees)
            holding_days: Number of calendar days held
            investor_type: 'INDIVIDUAL' or 'INSTITUTIONAL'

        Returns:
            CGT amount (0 if loss or no gain)
        """
        if net_gain <= 0:
            return 0.0

        if investor_type.upper() == "INSTITUTIONAL":
            return net_gain * 0.10  # 10% for institutional

        # Individual: 7.5% short term, 5% long term
        if holding_days < 365:
            return net_gain * NepseTradingEngine.CGT_SHORT_TERM_RATE
        else:
            return net_gain * NepseTradingEngine.CGT_LONG_TERM_RATE

    @staticmethod
    def calculate_holding_days(purchase_date: datetime.date, sell_date: datetime.date) -> int:
        """Calculate calendar days between purchase and sell dates."""
        return (sell_date - purchase_date).days

    @staticmethod
    def calculate_cgt_for_sell(qty: int, sell_price: float, wacc: float,
                              purchase_date: datetime.date, sell_date: datetime.date,
                              investor_type: str = "INDIVIDUAL") -> Dict[str, float]:
        """
        Calculate full CGT breakdown for a sell order.
        """
        holding_days = NepseTradingEngine.calculate_holding_days(purchase_date, sell_date)

        # Calculate fees (sell side)
        fees = NepseTradingEngine.calculate_fees(qty, sell_price, 'SELL')

        cost_basis = wacc * qty
        sell_gross = fees['gross']
        sell_fees = fees['total_fees']

        # Net gain = sell proceeds - fees - cost basis
        net_gain = sell_gross - sell_fees - cost_basis

        # Calculate CGT
        cgt = NepseTradingEngine.calculate_cgt(net_gain, holding_days, investor_type)

        net_received = sell_gross - sell_fees - cgt

        return {
            'holding_days': holding_days,
            'gross': fees['gross'],
            'fees': fees['total_fees'],
            'cost_basis': round(cost_basis, 2),
            'net_gain': round(net_gain, 2),
            'cgt_rate': '7.5%' if holding_days < 365 else '5%' if investor_type.upper() == "INDIVIDUAL" else '10%',
            'cgt': round(cgt, 2),
            'net_received': round(net_received, 2)
        }

    @staticmethod
    def calculate_break_even(wacc: float, qty: int, investor_type: str = "INDIVIDUAL") -> float:
        """
        Calculate break-even sell price using iterative method.

        Solves for price where: net_received = wacc * qty
        (sell_gross - sell_fees - cgt = wacc * qty)
        """
        p = wacc  # Initial guess

        for _ in range(100):
            gross = p * qty
            fees = NepseTradingEngine.calculate_fees(qty, p, 'SELL')

            # Calculate net gain to determine CGT
            cost_basis = wacc * qty
            net_gain = fees['gross'] - fees['total_fees'] - cost_basis
            cgt = NepseTradingEngine.calculate_cgt(net_gain, 365, investor_type)  # Use long term for safe side

            net_received = fees['gross'] - fees['total_fees'] - cgt
            needed = wacc * qty

            # Adjust price
            if abs(net_received - needed) < 0.01:
                break

            # Newton-like adjustment
            diff = (needed - net_received) / qty
            p = p + diff

            if p < 0:  # Prevent negative price
                p = wacc

        return round(p, 2)

    @staticmethod
    def calculate_price_band(prev_close: float) -> Tuple[float, float]:
        """
        Calculate upper and lower circuit price limits.

        Returns:
            Tuple of (upper_circuit, lower_circuit)
        """
        upper = round(prev_close * 1.10, 2)
        lower = round(prev_close * 0.90, 2)
        return upper, lower

    @staticmethod
    def validate_price(price: float, prev_close: float) -> Tuple[bool, str]:
        """
        Validate if price is within ±10% daily band.
        """
        upper, lower = NepseTradingEngine.calculate_price_band(prev_close)

        if price > upper:
            return False, f"Price Rs.{price} exceeds upper circuit limit Rs.{upper} (+10%)."
        if price < lower:
            return False, f"Price Rs.{price} below lower circuit limit Rs.{lower} (-10%)."

        return True, "Price is within valid range."

    @staticmethod
    def get_slab_info(gross_amount: float) -> Dict[str, Any]:
        """Get commission slab information for display."""
        for limit, rate in NepseTradingEngine.COMMISSION_SLABS:
            if gross_amount <= limit:
                return {
                    'rate': rate,
                    'rate_percent': f"{rate * 100:.3f}%",
                    'slab_label': f"Up to Rs. {limit:,.0f}" if limit < float('inf') else f"Above Rs. {10000000:,.0f}"
                }
        return {'rate': 0.00243, 'rate_percent': '0.243%', 'slab_label': 'Above Rs. 1 crore'}


# Account and Portfolio Engine
class TradingAccount:
    """
    Manages user account, holdings, and transactions.
    """

    def __init__(self, cash: float = 100000.0, investor_type: str = "INDIVIDUAL"):
        self.cash = cash
        self.investor_type = investor_type.upper()
        self.holdings: Dict[str, Dict] = {}  # symbol -> holding data
        self.pending_settlements: List[Dict] = []  # pending T+2 settlements
        self.transactions: List[Dict] = []  # trade history

    def get_holding(self, symbol: str) -> Optional[Dict]:
        """Get holding for a symbol."""
        return self.holdings.get(symbol)

    def can_sell(self, symbol: str, qty: int) -> Tuple[bool, str]:
        """
        Check if user can sell specified quantity.
        Validates settled quantity and T+2 rule.
        """
        holding = self.holdings.get(symbol)
        if not holding:
            return False, f"You don't own any shares of {symbol}."

        settled_qty = holding.get('settled_qty', 0)
        if qty > settled_qty:
            pending = holding.get('total_qty', 0) - settled_qty
            return False, f"Only {settled_qty} shares are settled. {pending} shares settle on {holding.get('settle_date', 'N/A')}."

        return True, "Can sell."

    def execute_buy(self, symbol: str, qty: int, price: float,
                    trade_date: datetime.datetime = None) -> Tuple[bool, str, Dict]:
        """
        Execute a buy order.

        Returns:
            Tuple of (success, message, trade_record)
        """
        if trade_date is None:
            trade_date = datetime.datetime.now()

        trade_date_only = trade_date.date()

        # Calculate settlement date (T+2)
        settle_date = NepseTradingEngine.calculate_settle_date(trade_date_only)

        # Calculate all costs
        costs = NepseTradingEngine.calculate_fees(qty, price, 'BUY')
        total_required = costs['total_paid']

        # Check cash
        if self.cash < total_required:
            return False, f"Insufficient cash. Required: Rs.{total_required:,.2f}, Available: Rs.{self.cash:,.2f}", {}

        # Deduct cash
        self.cash -= total_required

        # Update or create holding
        holding = self.holdings.get(symbol)

        if holding:
            # Update WACC (weighted average)
            old_qty = holding['total_qty']
            old_cost_basis = holding['total_cost_basis']
            new_cost_basis = price * qty + costs['total_fees']

            new_qty = old_qty + qty
            new_wacc = (old_cost_basis + new_cost_basis) / new_qty

            # Update holding
            holding['total_qty'] = new_qty
            holding['wacc'] = round(new_wacc, 2)
            holding['total_cost_basis'] = round(old_cost_basis + new_cost_basis, 2)
            holding['settled_qty'] = old_qty  # Settled qty doesn't change on buy
            # Keep existing settle_date for settled shares
        else:
            # Create new holding
            self.holdings[symbol] = {
                'symbol': symbol,
                'total_qty': qty,
                'settled_qty': 0,  # New purchases need T+2
                'wacc': round((price * qty + costs['total_fees']) / qty, 2),
                'total_cost_basis': round(price * qty + costs['total_fees'], 2),
                'purchase_date': trade_date_only,
                'settle_date': settle_date
            }

        # Add to pending settlements
        self.pending_settlements.append({
            'symbol': symbol,
            'qty': qty,
            'trade_date': trade_date_only,
            'settle_date': settle_date,
            'status': 'PENDING'
        })

        # Record transaction
        trade_record = {
            'id': len(self.transactions) + 1,
            'symbol': symbol,
            'type': 'BUY',
            'qty': qty,
            'price': price,
            'gross': costs['gross'],
            'commission': costs['commission'],
            'sebon_fee': costs['sebon'],
            'dp_fee': costs['dp'],
            'total_fees': costs['total_fees'],
            'total_paid': costs['total_paid'],
            'wacc': self.holdings[symbol]['wacc'],
            'trade_date': trade_date,
            'settle_date': settle_date
        }
        self.transactions.append(trade_record)

        return True, f"Bought {qty} shares of {symbol} @ Rs.{price}", trade_record

    def execute_sell(self, symbol: str, qty: int, price: float,
                     trade_date: datetime.datetime = None) -> Tuple[bool, str, Dict]:
        """
        Execute a sell order.

        Returns:
            Tuple of (success, message, trade_record)
        """
        if trade_date is None:
            trade_date = datetime.datetime.now()

        trade_date_only = trade_date.date()

        # Check if can sell (settled qty)
        can_sell, msg = self.can_sell(symbol, qty)
        if not can_sell:
            return False, msg, {}

        holding = self.holdings[symbol]

        # Calculate sell proceeds with CGT
        cgt_info = NepseTradingEngine.calculate_cgt_for_sell(
            qty, price, holding['wacc'],
            holding['purchase_date'], trade_date_only,
            self.investor_type
        )

        # Add cash
        self.cash += cgt_info['net_received']

        # Update holding
        new_total_qty = holding['total_qty'] - qty

        if new_total_qty == 0:
            # Remove holding
            del self.holdings[symbol]
        else:
            # Reduce quantities
            new_settled_qty = max(0, holding['settled_qty'] - qty)

            # Update (WACC stays same for remaining shares)
            holding['total_qty'] = new_total_qty
            holding['settled_qty'] = new_settled_qty
            # Note: We don't reduce total_cost_basis proportionally
            # WACC remains the same per NEPSE rules

        # Record transaction
        trade_record = {
            'id': len(self.transactions) + 1,
            'symbol': symbol,
            'type': 'SELL',
            'qty': qty,
            'price': price,
            'gross': cgt_info['gross'],
            'commission': price * qty * 0.0036,  # Approximate
            'sebon_fee': cgt_info['gross'] * 0.00015,
            'dp_fee': 25,
            'total_fees': cgt_info['fees'],
            'cgt': cgt_info['cgt'],
            'net_received': cgt_info['net_received'],
            'wacc': holding.get('wacc', 0) if symbol in self.holdings else 0,
            'holding_days': cgt_info['holding_days'],
            'trade_date': trade_date,
            'settle_date': trade_date.date()
        }
        self.transactions.append(trade_record)

        return True, f"Sold {qty} shares of {symbol} @ Rs.{price}", trade_record

    def run_settlement_job(self, current_date: datetime.date = None):
        """
        Process pending settlements.
        Move shares from pending to settled when T+2 is reached.
        """
        if current_date is None:
            current_date = datetime.datetime.now().date()

        # Process pending settlements
        for pending in list(self.pending_settlements):
            if pending['status'] == 'PENDING' and pending['settle_date'] <= current_date:
                # Settle the shares
                symbol = pending['symbol']
                qty = pending['qty']

                if symbol in self.holdings:
                    self.holdings[symbol]['settled_qty'] += qty
                    # Update settle date to earliest pending
                    if 'pending_settle' in self.holdings[symbol]:
                        del self.holdings[symbol]['pending_settle']

                pending['status'] = 'SETTLED'

        # Clean up settled entries
        self.pending_settlements = [p for p in self.pending_settlements if p['status'] == 'PENDING']

    def get_account_summary(self, market_prices: Dict[str, float] = None) -> Dict:
        """
        Get account summary including P&L.

        Args:
            market_prices: Dict of symbol -> current price
        """
        total_equity = 0
        total_investment = 0
        total_unrealized_pl = 0

        holdings_list = []

        for symbol, holding in self.holdings.items():
            qty = holding['total_qty']
            settled = holding['settled_qty']
            wacc = holding['wacc']
            cost_basis = holding['total_cost_basis']

            current_price = market_prices.get(symbol, wacc) if market_prices else wacc
            current_value = qty * current_price
            unrealized_pl = current_value - cost_basis
            unrealized_pl_pct = (unrealized_pl / cost_basis * 100) if cost_basis > 0 else 0

            total_equity += current_value
            total_investment += cost_basis
            total_unrealized_pl += unrealized_pl

            holdings_list.append({
                'symbol': symbol,
                'total_qty': qty,
                'settled_qty': settled,
                'pending_qty': qty - settled,
                'wacc': wacc,
                'cost_basis': cost_basis,
                'ltp': current_price,
                'current_value': current_value,
                'unrealized_pl': unrealized_pl,
                'unrealized_pl_pct': unrealized_pl_pct,
                'is_odd_lot': qty % 10 != 0
            })

        return {
            'cash': round(self.cash, 2),
            'total_equity': round(total_equity, 2),
            'net_worth': round(self.cash + total_equity, 2),
            'total_investment': round(total_investment, 2),
            'unrealized_pl': round(total_unrealized_pl, 2),
            'unrealized_pl_pct': round((total_unrealized_pl / total_investment * 100) if total_investment > 0 else 0, 2),
            'holdings': holdings_list,
            'pending_settlements': self.pending_settlements
        }


# Order Management System
class OrderManager:
    """Manages orders (market, limit, stop-loss)."""

    ORDER_TYPES = ['MARKET', 'LIMIT', 'STOP_LOSS']
    ORDER_SIDES = ['BUY', 'SELL']
    VALIDITY_OPTIONS = ['EOD', 'GTC']

    def __init__(self, account: TradingAccount):
        self.account = account
        self.orders: List[Dict] = []

    def place_market_order(self, symbol: str, side: str, qty: int,
                          current_price: float, prev_close: float) -> Tuple[bool, str, Dict]:
        """Place a market order."""
        return self._place_order(symbol, side, qty, current_price, 'MARKET', None, 'EOD', prev_close)

    def place_limit_order(self, symbol: str, side: str, qty: int,
                         limit_price: float, validity: str, prev_close: float) -> Tuple[bool, str, Dict]:
        """Place a limit order."""
        return self._place_order(symbol, side, qty, limit_price, 'LIMIT', limit_price, validity, prev_close)

    def place_stop_loss(self, symbol: str, side: str, qty: int,
                       stop_price: float, validity: str, prev_close: float) -> Tuple[bool, str, Dict]:
        """Place a stop-loss order."""
        return self._place_order(symbol, side, qty, stop_price, 'STOP_LOSS', stop_price, validity, prev_close)

    def _place_order(self, symbol: str, side: str, qty: int, price: float,
                    order_type: str, limit_price: float, validity: str, prev_close: float) -> Tuple[bool, str, Dict]:
        """Internal order placement."""
        # Validate order type
        if order_type not in self.ORDER_TYPES:
            return False, f"Invalid order type: {order_type}", {}
        if side not in self.ORDER_SIDES:
            return False, f"Invalid side: {side}", {}
        if validity not in self.VALIDITY_OPTIONS:
            return False, f"Invalid validity: {validity}", {}

        # For LIMIT and STOP_LOSS, validate price band
        if order_type != 'MARKET':
            is_valid, msg = NepseTradingEngine.validate_price(limit_price, prev_close)
            if not is_valid:
                return False, msg, {}
        else:
            # For market orders, validate current price is in band
            is_valid, msg = NepseTradingEngine.validate_price(price, prev_close)
            if not is_valid:
                return False, msg, {}

        # For BUY: validate cash
        if side == 'BUY':
            costs = NepseTradingEngine.calculate_fees(qty, price if order_type == 'MARKET' else limit_price, 'BUY')
            if self.account.cash < costs['total_paid']:
                return False, f"Insufficient cash. Need Rs.{costs['total_paid']:,.2f}", {}

        # For SELL: validate settled qty
        if side == 'SELL':
            can_sell, msg = self.account.can_sell(symbol, qty)
            if not can_sell:
                return False, msg, {}

        # Create order
        order = {
            'id': len(self.orders) + 1,
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'order_type': order_type,
            'price': price if order_type == 'MARKET' else limit_price,
            'stop_price': limit_price if order_type == 'STOP_LOSS' else None,
            'validity': validity,
            'status': 'OPEN',
            'created_at': datetime.datetime.now(),
            'expires_at': self._calculate_expiry(validity)
        }

        self.orders.append(order)

        return True, f"Order placed: {side} {qty} {symbol} @ {'MKT' if order_type == 'MARKET' else limit_price}", order

    def _calculate_expiry(self, validity: str) -> datetime.datetime:
        """Calculate order expiry datetime."""
        now = datetime.datetime.now()

        if validity == 'EOD':
            # Expires at market close (3:00 PM) today
            today = now.date()
            expiry_time = datetime.time(15, 0)
            return datetime.datetime.combine(today, expiry_time)
        else:  # GTC
            # Expires after 15 calendar days
            return now + datetime.timedelta(days=15)

    def cancel_order(self, order_id: int) -> Tuple[bool, str]:
        """Cancel an order."""
        for order in self.orders:
            if order['id'] == order_id:
                if order['status'] != 'OPEN':
                    return False, f"Order {order_id} is not open (status: {order['status']})"

                order['status'] = 'CANCELLED'
                return True, f"Order {order_id} cancelled"

        return False, f"Order {order_id} not found"

    def get_open_orders(self) -> List[Dict]:
        """Get all open orders."""
        return [o for o in self.orders if o['status'] == 'OPEN']

    def check_limit_orders(self, symbol: str, current_price: float) -> List[Dict]:
        """Check if any limit/stop orders should execute."""
        triggered = []

        for order in self.orders:
            if order['symbol'] != symbol or order['status'] != 'OPEN':
                continue

            # Check expiry first
            if datetime.datetime.now() > order['expires_at']:
                order['status'] = 'EXPIRED'
                continue

            # Check trigger
            if order['order_type'] == 'LIMIT':
                if order['side'] == 'BUY' and current_price <= order['price']:
                    triggered.append(order)
                elif order['side'] == 'SELL' and current_price >= order['price']:
                    triggered.append(order)
            elif order['order_type'] == 'STOP_LOSS':
                if order['side'] == 'SELL' and current_price <= order['stop_price']:
                    triggered.append(order)
                elif order['side'] == 'BUY' and current_price >= order['stop_price']:
                    triggered.append(order)

        return triggered

    def run_expiry_job(self, current_date: datetime.date = None):
        """Process order expirations."""
        if current_date is None:
            current_date = datetime.datetime.now().date()

        now = datetime.datetime.now()

        for order in self.orders:
            if order['status'] == 'OPEN' and now > order['expires_at']:
                order['status'] = 'EXPIRED'