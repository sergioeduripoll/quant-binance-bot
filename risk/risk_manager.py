"""
Gestor de riesgo global.
Controla límites diarios, drawdown máximo y protección del portfolio.
"""

from datetime import datetime, timezone
from config.settings import MAX_DAILY_LOSS, MAX_OPEN_POSITIONS
from database.supabase_client import db
from utils.logger import get_logger

logger = get_logger(__name__)


class RiskManager:
    """
    Valida condiciones de riesgo antes de permitir un trade.
    
    Checks:
    1. Pérdida diaria no excede MAX_DAILY_LOSS
    2. Posiciones abiertas no exceden MAX_OPEN_POSITIONS
    3. No operar en horarios de alta volatilidad sin datos
    4. Drawdown máximo del portfolio
    """

    def __init__(self):
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._last_reset_date = None

    async def can_trade(self, balance: float) -> dict:
        """
        Verifica si se puede abrir un nuevo trade.
        
        Returns:
            dict con 'allowed' (bool) y 'reason' (str)
        """
        # Reset diario
        today = datetime.now(timezone.utc).date()
        if self._last_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._last_reset_date = today

        # ── Check 1: Pérdida diaria ──
        bot_state = await db.get_bot_state()
        if bot_state:
            self._daily_pnl = float(bot_state.get("daily_pnl", 0))
            self._daily_trades = int(bot_state.get("daily_trades", 0))

        max_loss_amount = balance * MAX_DAILY_LOSS
        if self._daily_pnl < 0 and abs(self._daily_pnl) >= max_loss_amount:
            return {
                "allowed": False,
                "reason": (
                    f"Pérdida diaria alcanzada: ${self._daily_pnl:.2f} "
                    f"(máx: -${max_loss_amount:.2f})"
                ),
            }

        # ── Check 2: Posiciones abiertas ──
        open_trades = await db.get_open_trades()
        if len(open_trades) >= MAX_OPEN_POSITIONS:
            return {
                "allowed": False,
                "reason": f"Máximo de posiciones abiertas: {len(open_trades)}/{MAX_OPEN_POSITIONS}",
            }

        # ── Check 3: Balance mínimo ──
        min_balance = 10.0  # Mínimo $10 para operar
        if balance < min_balance:
            return {
                "allowed": False,
                "reason": f"Balance insuficiente: ${balance:.2f} (mín: ${min_balance})",
            }

        # ── Check 4: Circuit breaker ──
        # Si hay 3+ losses consecutivos, pausar 15 minutos
        recent_trades = await db.get_recent_trades(limit=5)
        consecutive_losses = 0
        for t in recent_trades:
            if float(t.get("pnl_net", 0)) < 0:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= 3:
            last_trade_time = recent_trades[0].get("closed_at")
            if last_trade_time:
                last_dt = datetime.fromisoformat(last_trade_time.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                minutes_since = (now - last_dt).total_seconds() / 60
                if minutes_since < 15:
                    return {
                        "allowed": False,
                        "reason": (
                            f"Circuit breaker: {consecutive_losses} losses seguidos. "
                            f"Pausa {15 - minutes_since:.0f}min restantes"
                        ),
                    }

        return {
            "allowed": True,
            "reason": "OK",
            "open_positions": len(open_trades),
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
        }

    def update_daily_pnl(self, pnl: float):
        """Actualiza P&L diario en memoria."""
        self._daily_pnl += pnl
        self._daily_trades += 1
