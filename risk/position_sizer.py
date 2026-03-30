"""
Calculador de tamaño de posición y apalancamiento dinámico.
Gestiona el capital de forma profesional según confianza de la señal.
"""

from config.settings import (
    MAX_RISK_PER_TRADE, MAX_OPEN_POSITIONS, MAX_LEVERAGE, DEFAULT_LEVERAGE
)
from risk.commission_calc import CommissionCalculator
from utils.logger import get_logger
from utils.helpers import round_quantity, round_price

logger = get_logger(__name__)


class PositionSizer:
    """
    Calcula tamaño de posición usando el método de riesgo fijo.
    
    Fórmula:
    1. Riesgo máximo = Balance × MAX_RISK_PER_TRADE
    2. Distancia al SL en precio
    3. Cantidad = Riesgo máximo / Distancia SL
    4. Apalancamiento ajustado por confianza
    5. Validación de comisiones pre-trade
    """

    def __init__(self):
        self.commission_calc = CommissionCalculator()

    def calculate(
        self,
        balance: float,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        side: str,
        confidence: float,
        pair_config: dict,
        open_positions: int = 0,
    ) -> dict | None:
        """
        Calcula tamaño de posición óptimo.
        
        Returns:
            dict con quantity, leverage, notional, margin_required
            None si el trade no es válido
        """
        if open_positions >= MAX_OPEN_POSITIONS:
            logger.warning(f"Máximo de posiciones abiertas ({MAX_OPEN_POSITIONS})")
            return None

        if balance <= 0:
            logger.warning("Balance insuficiente")
            return None

        # ── 1. Calcular riesgo máximo permitido ──
        # Reducir riesgo si ya hay posiciones abiertas
        position_factor = 1.0 - (open_positions * 0.2)
        max_risk = balance * MAX_RISK_PER_TRADE * position_factor

        # ── 2. Ajustar apalancamiento por confianza ──
        leverage = self._dynamic_leverage(confidence, pair_config)

        # ── 3. Calcular distancia al SL ──
        if side == "LONG":
            sl_distance = entry_price - sl_price
        else:
            sl_distance = sl_price - entry_price

        if sl_distance <= 0:
            logger.warning(f"SL distance inválida: {sl_distance}")
            return None

        # ── 4. Calcular cantidad ──
        # quantity = riesgo_max / distancia_sl
        quantity = max_risk / sl_distance

        # Redondear según precisión del par
        qty_precision = pair_config.get("qty_precision", 3)
        price_precision = pair_config.get("price_precision", 2)
        quantity = round_quantity(quantity, qty_precision)

        if quantity <= 0:
            logger.warning("Cantidad calculada es 0 tras redondeo")
            return None

        # ── 5. Calcular notional y margen ──
        notional = entry_price * quantity
        margin_required = notional / leverage

        # Verificar que el margen no exceda un % del balance
        max_margin_pct = 0.3  # No más del 30% del balance por trade
        if margin_required > balance * max_margin_pct:
            # Reducir cantidad
            quantity = round_quantity(
                (balance * max_margin_pct * leverage) / entry_price,
                qty_precision
            )
            notional = entry_price * quantity
            margin_required = notional / leverage

        # ── 6. Validar comisiones ──
        validation = self.commission_calc.validate_trade(
            entry_price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            quantity=quantity,
            side=side,
        )

        if not validation["is_valid"]:
            logger.warning(
                f"Trade no pasa validación de comisiones: "
                f"net_profit={validation['net_profit']:.4f} "
                f"fee_ratio={validation['fee_to_profit_ratio']:.2f}"
            )
            return None

        result = {
            "quantity": quantity,
            "leverage": leverage,
            "notional_value": round(notional, 2),
            "margin_required": round(margin_required, 2),
            "risk_amount": round(max_risk, 2),
            "risk_percentage": round(MAX_RISK_PER_TRADE * 100 * position_factor, 2),
            "commission_validation": validation,
        }

        logger.info(
            f"Position sized: qty={quantity} lev={leverage}x "
            f"notional=${notional:.2f} margin=${margin_required:.2f} "
            f"risk=${max_risk:.2f}"
        )

        return result

    def _dynamic_leverage(self, confidence: float, pair_config: dict) -> int:
        """
        Calcula apalancamiento dinámico basado en confianza.
        
        Alta confianza (>0.80) → leverage preferido del par
        Media (0.65-0.80) → 70% del preferido
        Baja (0.55-0.65) → 50% del preferido
        """
        max_lev = min(pair_config.get("max_leverage", 20), MAX_LEVERAGE)
        preferred = pair_config.get("preferred_leverage", DEFAULT_LEVERAGE)

        if confidence >= 0.80:
            lev = preferred
        elif confidence >= 0.65:
            lev = int(preferred * 0.7)
        else:
            lev = int(preferred * 0.5)

        return max(3, min(lev, max_lev))
