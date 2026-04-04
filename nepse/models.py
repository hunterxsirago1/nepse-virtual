from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import json

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, default='default_user')
    virtual_cash = db.Column(db.Float, nullable=False, default=100000.0)
    investor_type = db.Column(db.String(20), nullable=False, default='INDIVIDUAL')  # INDIVIDUAL or INSTITUTIONAL

    holdings = db.relationship('Holding', backref='user', lazy=True, cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', backref='user', lazy=True, cascade='all, delete-orphan')
    pending_settlements = db.relationship('PendingSettlement', backref='user', lazy=True, cascade='all, delete-orphan')
    orders = db.relationship('Order', backref='user', lazy=True, cascade='all, delete-orphan')
    watchlist = db.relationship('Watchlist', backref='user', lazy=True, cascade='all, delete-orphan')


class Holding(db.Model):
    """Stock holding with WACC and settlement tracking."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False, index=True)

    total_qty = db.Column(db.Integer, nullable=False, default=0)
    settled_qty = db.Column(db.Integer, nullable=False, default=0)
    # pending_qty = total_qty - settled_qty

    wacc = db.Column(db.Float, nullable=False, default=0.0)  # Weighted Average Cost per share (including fees)
    total_cost_basis = db.Column(db.Float, nullable=False, default=0.0)  # Total cost including all fees

    purchase_date = db.Column(db.Date, nullable=False, default=date.today)
    # Note: For mixed lots, this represents the earliest purchase date

    # For WACC calculation after multiple buys
    # WACC = (old_cost_basis + new_buy_cost) / (old_qty + new_qty)
    # We store purchase_date of FIRST lot for holding period calculation

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'total_qty': self.total_qty,
            'settled_qty': self.settled_qty,
            'pending_qty': self.total_qty - self.settled_qty,
            'wacc': round(self.wacc, 2),
            'total_cost_basis': round(self.total_cost_basis, 2),
            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,
            'is_odd_lot': self.total_qty % 10 != 0
        }


class PendingSettlement(db.Model):
    """Tracks shares pending T+2 settlement."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    trade_date = db.Column(db.Date, nullable=False)
    settle_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PENDING')  # PENDING, SETTLED

    def to_dict(self):
        days_until = (self.settle_date - date.today()).days if self.settle_date else 0
        return {
            'id': self.id,
            'symbol': self.symbol,
            'qty': self.qty,
            'trade_date': self.trade_date.isoformat() if self.trade_date else None,
            'settle_date': self.settle_date.isoformat() if self.settle_date else None,
            'days_until_settle': days_until,
            'status': self.status
        }


class Transaction(db.Model):
    """Executed trade record with full fee breakdown."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'BUY' or 'SELL'

    qty = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)

    gross = db.Column(db.Float)  # qty * price
    commission = db.Column(db.Float)
    sebon_fee = db.Column(db.Float)
    dp_fee = db.Column(db.Float)
    total_fees = db.Column(db.Float)
    cgt = db.Column(db.Float, default=0.0)  # Only for SELL

    # For BUY: total_paid = gross + fees
    # For SELL: net_received = gross - fees - cgt
    total_paid = db.Column(db.Float)  # For BUY
    net_received = db.Column(db.Float)  # For SELL

    # WACC at time of trade
    wacc = db.Column(db.Float)

    # For SELL: holding period
    holding_days = db.Column(db.Integer)

    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    trade_date = db.Column(db.Date)
    settle_date = db.Column(db.Date)

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'type': self.type,
            'qty': self.qty,
            'price': round(self.price, 2),
            'gross': round(self.gross, 2),
            'commission': round(self.commission, 2),
            'sebon_fee': round(self.sebon_fee, 2),
            'dp_fee': round(self.dp_fee, 2),
            'total_fees': round(self.total_fees, 2),
            'cgt': round(self.cgt or 0, 2),
            'total_paid': round(self.total_paid or 0, 2),
            'net_received': round(self.net_received or 0, 2),
            'wacc': round(self.wacc, 2) if self.wacc else 0,
            'holding_days': self.holding_days,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M') if self.timestamp else None,
            'trade_date': self.trade_date.isoformat() if self.trade_date else None,
            'settle_date': self.settle_date.isoformat() if self.settle_date else None
        }


class Order(db.Model):
    """Pending orders (limit, stop-loss)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)

    side = db.Column(db.String(10), nullable=False)  # BUY or SELL
    order_type = db.Column(db.String(20), nullable=False)  # MARKET, LIMIT, STOP_LOSS

    qty = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)  # For LIMIT: limit price; For STOP_LOSS: stop price

    # For STOP_LOSS: when triggered, executes at market
    validity = db.Column(db.String(10), nullable=False)  # EOD or GTC

    status = db.Column(db.String(20), nullable=False, default='OPEN')  # OPEN, EXECUTED, CANCELLED, EXPIRED

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    executed_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side,
            'order_type': self.order_type,
            'qty': self.qty,
            'price': round(self.price, 2),
            'validity': self.validity,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
            'executed_at': self.executed_at.strftime('%Y-%m-%d %H:%M') if self.executed_at else None,
            'expires_at': self.expires_at.strftime('%Y-%m-%d %H:%M') if self.expires_at else None
        }


class Watchlist(db.Model):
    """User's watchlist."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class Holiday(db.Model):
    """Admin-managed Nepal public holidays."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'date': self.date.isoformat(),
            'name': self.name,
            'is_active': self.is_active
        }