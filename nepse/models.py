from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, default='default_user')
    balance = db.Column(db.Float, nullable=False, default=100000.0)
    holdings = db.relationship('Holding', backref='user', lazy=True)
    transactions = db.relationship('Transaction', backref='user', lazy=True)

class Holding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    wacc = db.Column(db.Float, nullable=False)  # Weighted Average Cost of Capital
    purchase_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'BUY' or 'SELL'
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    commission = db.Column(db.Float)
    sebon_fee = db.Column(db.Float)
    dp_fee = db.Column(db.Float)
    cgt = db.Column(db.Float)
    total_amount = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
