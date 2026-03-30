"""
Calculadora de comisiones de Binance Futures.
Valida que un trade tenga sentido matemático ANTES de entrar.
"""

from config.settings import MAKER_FEE, TAKER_FEE
from utils.logger import get_logger

logger = get_logger(__name__)


class CommissionCalculator:
    """
    Calcula comisiones exactas de Binance Futures.
    
    Binance Futures fees (VIP 0):
    - Maker: 0.0200% (limit orders)
    - Taker: 0.0400% (market orders)
    
    Un scalp trade típico:
    - Entrada: Market order (taker)
    - Salida: Limit order (maker) si es TP, Market (taker) si es SL
    """

    def __init__(
        self,
        maker_fee: float = MAKER_FEE,
        taker_fee: float = TAKER_FEE,
    ):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee

    def entry_commission(
        self,
        price: float,
        quantity: float,
        is_maker: bool = False,
    ) -> float:
        """Comisión de entrada."""
        notional = price * quantity
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        return notional * fee_rate

    def exit_commission(
        self,
        price: float,
        quantity: float,
        is_maker: bool = True,
    ) -> float:
        """Comisión de salida."""
        notional = price * quantity
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        return notional * fee_rate

    def total_round_trip(
        self,
        entry_price: float,
        exit_price: float,
        quantity: float,
        entry_maker: bool = False,
        exit_maker: bool = True,
    ) -> float:
        """Comisión total de ida y vuelta."""
        entry = self.entry_commission(entry_price, quantity, entry_maker)
        exit_ = self.exit_commission(exit_price, quantity, exit_maker)
        return entry + exit_

    def min_profit_target(
        self,
        entry_price: float,
        quantity: float,
        profit_multiple: float = 1.5,
    ) -> float:
        """
        Calcula el movimiento mínimo de precio para cubrir comisiones.
        
        profit_multiple: cuántas veces las comisiones queremos ganar mínimo.
        1.5 = ganamos al menos 1.5x lo que pagamos en comisiones.
        """
        # Peor caso: entry taker + exit taker
        worst_case_fees = (
            entry_price * quantity * self.taker_fee * 2
        )
        min_profit = worst_case_fees * profit_multiple
        # Convertir a movimiento de precio
        min_price_move = min_profit / quantity
        return min_price_move

    def validate_trade(
        self,
        entry_price: float,
        tp_price: float,
        sl_price: float,
        quantity: float,
        side: str,
        min_profit_ratio: float = 1.5,
    ) -> dict:
        """
        Valida que un trade tenga sentido matemático.
        
        Retorna dict con:
        - is_valid: bool
        - expected_profit: ganancia bruta si TP
        - total_fees: comisiones totales
        - net_profit: ganancia neta
        - fee_to_profit_ratio: ratio comisiones/ganancia
        - min_price_move: movimiento mínimo necesario
        """
        # Calcular ganancia bruta al TP
        if side == "LONG":
            gross_profit = (tp_price - entry_price) * quantity
            gross_loss = (entry_price - sl_price) * quantity
        else:
            gross_profit = (entry_price - tp_price) * quantity
            gross_loss = (sl_price - entry_price) * quantity

        # Comisiones (entrada taker, salida maker para TP)
        fees_if_tp = self.total_round_trip(
            entry_price, tp_price, quantity,
            entry_maker=False, exit_maker=True,
        )
        fees_if_sl = self.total_round_trip(
            entry_price, sl_price, quantity,
            entry_maker=False, exit_maker=False,  # SL es market = taker
        )

        net_profit = gross_profit - fees_if_tp
        net_loss = gross_loss + fees_if_sl
        min_move = self.min_profit_target(entry_price, quantity, min_profit_ratio)

        # Ratio de comisiones sobre ganancia
        fee_ratio = fees_if_tp / gross_profit if gross_profit > 0 else float("inf")

        is_valid = (
            net_profit > 0
            and fee_ratio < 0.5  # Comisiones no superan 50% de ganancia
            and abs(tp_price - entry_price) >= min_move
        )

        result = {
            "is_valid": is_valid,
            "gross_profit": gross_profit,
            "total_fees_tp": fees_if_tp,
            "total_fees_sl": fees_if_sl,
            "net_profit": net_profit,
            "net_loss": -net_loss,
            "fee_to_profit_ratio": fee_ratio,
            "min_price_move": min_move,
            "risk_reward": net_profit / net_loss if net_loss > 0 else 0,
        }

        if not is_valid:
            logger.warning(
                f"Trade inválido: fees={fees_if_tp:.4f} "
                f"net_profit={net_profit:.4f} ratio={fee_ratio:.2f}"
            )

        return result
