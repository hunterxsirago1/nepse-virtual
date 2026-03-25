import datetime
import math

class NepseTradingEngine:
    # Commission Slabs effective from Jestha 1, 2081 (May 14, 2024)
    COMMISSION_SLABS = [
        (50000, 0.0036),
        (500000, 0.0033),
        (2000000, 0.0031),
        (10000000, 0.0027),
        (float('inf'), 0.0024)
    ]
    
    SEBON_FEE_RATE = 0.00015  # 0.015%
    DP_CHARGE = 25.0         # Rs. 25 per script
    
    @staticmethod
    def calculate_broker_commission(amount):
        """Calculates tiered broker commission based on transaction amount."""
        for limit, rate in NepseTradingEngine.COMMISSION_SLABS:
            if amount <= limit:
                return amount * rate
        return amount * 0.0024

    @staticmethod
    def calculate_buy_costs(price, quantity):
        """
        Calculates total cost for buying shares including all fees.
        Total = Amount + Commission + SEBON Fee + DP Fee
        """
        share_amount = price * quantity
        commission = NepseTradingEngine.calculate_broker_commission(share_amount)
        sebon_fee = share_amount * NepseTradingEngine.SEBON_FEE_RATE
        dp_fee = NepseTradingEngine.DP_CHARGE
        
        total_cost = float(share_amount) + float(commission) + float(sebon_fee) + float(dp_fee)
        return {
            'share_amount': round(float(share_amount), 2),
            'commission': round(float(commission), 2),
            'sebon_fee': round(float(sebon_fee), 2),
            'dp_fee': round(float(dp_fee), 2),
            'total_cost': round(float(total_cost), 2)
        }

    @staticmethod
    def calculate_sell_costs(price, quantity, wacc, holding_days):
        """
        Calculates net receivable for selling shares including fees and CGT.
        Net = Amount - Commission - SEBON Fee - DP Fee - CGT
        """
        share_amount = price * quantity
        commission = NepseTradingEngine.calculate_broker_commission(share_amount)
        sebon_fee = share_amount * NepseTradingEngine.SEBON_FEE_RATE
        dp_fee = NepseTradingEngine.DP_CHARGE
        
        # Gross Receivable before Tax
        gross_receivable = share_amount - commission - sebon_fee - dp_fee
        
        # Capital Gains Tax (CGT)
        # Profit = Gross Receivable (selling) - Cost Price (buying)
        # Note: Cost price also included fees when bought (WACC)
        cost_price = wacc * quantity
        profit = share_amount - commission - sebon_fee - dp_fee - cost_price
        
        cgt = 0.0
        if profit > 0:
            tax_rate = 0.075 if holding_days < 365 else 0.05
            cgt = profit * tax_rate
            
        net_receivable = float(gross_receivable) - float(cgt)
        
        return {
            'share_amount': round(float(share_amount), 2),
            'commission': round(float(commission), 2),
            'sebon_fee': round(float(sebon_fee), 2),
            'dp_fee': round(float(dp_fee), 2),
            'profit': round(float(profit), 2),
            'cgt': round(float(cgt), 2),
            'net_receivable': round(float(net_receivable), 2)
        }

    @staticmethod
    def is_market_open():
        """
        Checks if the market is currently open.
        NEPSE Hours: Sun-Thu, 11:00 AM - 3:00 PM
        """
        # FOR SIMULATOR: Always open for testing
        return True, "Market is Open (Simulator Mode)."
