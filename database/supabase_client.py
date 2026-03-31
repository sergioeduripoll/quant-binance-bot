"""
Cliente Supabase centralizado.
Maneja todas las operaciones CRUD con la base de datos.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_SERVICE_KEY
from utils.logger import get_logger

logger = get_logger(__name__)


class SupabaseClient:
    """Cliente singleton para interactuar con Supabase."""

    _instance: "SupabaseClient | None" = None
    _client: Client | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self):
        """Inicializa la conexión con Supabase."""
        if self._client is None:
            url_preview = SUPABASE_URL[:40] if SUPABASE_URL else "(VACÍO)"
            key_preview = SUPABASE_SERVICE_KEY[:15] + "..." if SUPABASE_SERVICE_KEY else "(VACÍO)"
            logger.info(f"Connecting to Supabase: URL={url_preview} KEY={key_preview}")

            if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
                raise ValueError("Supabase credentials missing")

            self._client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            logger.info("Supabase client initialized")

    @property
    def client(self) -> Client:
        if self._client is None:
            self.initialize()
        return self._client

    # ── Trades ─────────────────────────────────────────────

    async def insert_trade(self, trade_data: dict) -> dict | None:
        """Inserta un nuevo trade y retorna el registro."""
        try:
            result = self.client.table("futures_trades").insert(trade_data).execute()
            if result.data:
                logger.info(f"Trade insertado: {result.data[0]['id']}")
                return result.data[0]
            else:
                logger.warning(f"Trade insert retornó data vacía")
        except Exception as e:
            logger.error(f"Error insertando trade: {e}", exc_info=True)
        return None

    async def update_trade(self, trade_id: str, update_data: dict) -> dict | None:
        """Actualiza un trade existente."""
        try:
            update_data["closed_at"] = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("futures_trades")
                .update(update_data)
                .eq("id", trade_id)
                .execute()
            )
            if result.data:
                logger.info(f"Trade actualizado: {trade_id}")
                return result.data[0]
        except Exception as e:
            logger.error(f"Error actualizando trade {trade_id}: {e}", exc_info=True)
        return None

    async def get_open_trades(self, symbol: str = None) -> list[dict]:
        """Obtiene trades abiertos, opcionalmente filtrados por símbolo."""
        try:
            query = (
                self.client.table("futures_trades")
                .select("*")
                .eq("status", "OPEN")
            )
            if symbol:
                query = query.eq("symbol", symbol)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error obteniendo trades abiertos: {e}")
            return []

    async def get_recent_trades(self, limit: int = 100) -> list[dict]:
        """Obtiene trades recientes para análisis ML."""
        try:
            result = (
                self.client.table("futures_trades")
                .select("*")
                .eq("status", "CLOSED")
                .order("closed_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Error obteniendo trades recientes: {e}")
            return []

    async def get_trade_count(self) -> int:
        """Cuenta total de trades cerrados (para fase de prueba)."""
        try:
            result = (
                self.client.table("futures_trades")
                .select("id", count="exact")
                .eq("status", "CLOSED")
                .execute()
            )
            return result.count or 0
        except Exception as e:
            logger.error(f"Error contando trades: {e}")
            return 0

    # ── Candles ────────────────────────────────────────────

    async def insert_candle(self, candle_data: dict) -> None:
        """Inserta o actualiza una vela con sus indicadores."""
        try:
            result = self.client.table("futures_candles").upsert(
                candle_data, on_conflict="symbol,open_time"
            ).execute()
            if result.data:
                logger.info(
                    f"✅ Candle saved: {candle_data.get('symbol')} | "
                    f"open_time={candle_data.get('open_time')} | "
                    f"close={candle_data.get('close')}"
                )
        except Exception as e:
            logger.error(
                f"❌ Error insertando vela {candle_data.get('symbol')}: {e}",
                exc_info=True,
            )

    async def get_candles(self, symbol: str, limit: int = 200) -> list[dict]:
        """Obtiene las últimas N velas de un símbolo."""
        try:
            result = (
                self.client.table("futures_candles")
                .select("*")
                .eq("symbol", symbol)
                .order("open_time", desc=True)
                .limit(limit)
                .execute()
            )
            return list(reversed(result.data or []))
        except Exception as e:
            logger.error(f"Error obteniendo velas {symbol}: {e}")
            return []

    # ── Signals ────────────────────────────────────────────

    async def insert_signal(self, signal_data: dict) -> dict | None:
        """Registra una señal generada."""
        try:
            result = (
                self.client.table("futures_signals").insert(signal_data).execute()
            )
            if result.data:
                logger.info(
                    f"Signal saved: {signal_data.get('symbol')} "
                    f"{signal_data.get('signal_type')} "
                    f"conf={signal_data.get('confidence')}"
                )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error insertando señal: {e}", exc_info=True)
            return None

    # ── Bot State & Wallet ─────────────────────────────────

    async def get_bot_state(self) -> dict | None:
        """Obtiene el estado actual del bot."""
        try:
            result = (
                self.client.table("futures_bot_state")
                .select("*")
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error obteniendo estado del bot: {e}")
            return None

    async def update_bot_state(self, update_data: dict) -> None:
        """Actualiza el estado del bot."""
        try:
            update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            state = await self.get_bot_state()
            if state:
                self.client.table("futures_bot_state").update(update_data).eq(
                    "id", state["id"]
                ).execute()
        except Exception as e:
            logger.error(f"Error actualizando estado del bot: {e}")

    async def update_wallet_balance(self, pnl_net: float) -> float:
        """
        Actualiza el balance de la wallet virtual sumando el P&L neto.

        Args:
            pnl_net: Ganancia/pérdida neta del trade (puede ser negativa)

        Returns:
            El nuevo balance después de la actualización
        """
        try:
            state = await self.get_bot_state()
            if not state:
                logger.error("No se encontró bot_state para actualizar balance")
                return 0.0

            old_balance = float(state.get("total_balance", 0))
            new_balance = old_balance + pnl_net

            # Calcular max drawdown
            max_dd = float(state.get("max_drawdown", 0))
            if new_balance < old_balance and old_balance > 0:
                current_dd = (old_balance - new_balance) / old_balance
                max_dd = max(max_dd, current_dd)

            # Calcular avg_win y avg_loss
            total_wins = int(state.get("total_wins", 0))
            total_losses = int(state.get("total_losses", 0))
            old_avg_win = float(state.get("avg_win", 0))
            old_avg_loss = float(state.get("avg_loss", 0))

            if pnl_net > 0:
                new_avg_win = (
                    (old_avg_win * total_wins + pnl_net) / (total_wins + 1)
                    if total_wins >= 0
                    else pnl_net
                )
                updates = {"avg_win": round(new_avg_win, 8)}
            else:
                new_avg_loss = (
                    (old_avg_loss * total_losses + pnl_net) / (total_losses + 1)
                    if total_losses >= 0
                    else pnl_net
                )
                updates = {"avg_loss": round(new_avg_loss, 8)}

            # Calcular profit factor
            total_gross_wins = old_avg_win * total_wins + (pnl_net if pnl_net > 0 else 0)
            total_gross_losses = abs(old_avg_loss * total_losses) + (abs(pnl_net) if pnl_net < 0 else 0)
            profit_factor = (
                total_gross_wins / total_gross_losses
                if total_gross_losses > 0
                else 0
            )

            updates.update({
                "total_balance": round(new_balance, 4),
                "available_balance": round(new_balance, 4),
                "max_drawdown": round(max_dd, 4),
                "profit_factor": round(profit_factor, 4),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

            self.client.table("futures_bot_state").update(updates).eq(
                "id", state["id"]
            ).execute()

            logger.info(
                f"💰 Wallet: ${old_balance:.2f} → ${new_balance:.2f} "
                f"(PnL: {'+' if pnl_net >= 0 else ''}{pnl_net:.4f})"
            )

            return new_balance

        except Exception as e:
            logger.error(f"Error actualizando wallet: {e}", exc_info=True)
            state = await self.get_bot_state()
            return float(state.get("total_balance", 0)) if state else 0.0

    # ── Trailing History ───────────────────────────────────

    async def insert_trailing_event(self, event_data: dict) -> None:
        """Registra un evento de trailing stop."""
        try:
            self.client.table("futures_trailing_history").insert(event_data).execute()
        except Exception as e:
            logger.error(f"Error insertando evento trailing: {e}")

    # ── ML Runs ────────────────────────────────────────────

    async def insert_ml_run(self, run_data: dict) -> None:
        """Registra una corrida de entrenamiento ML."""
        try:
            self.client.table("futures_ml_runs").insert(run_data).execute()
        except Exception as e:
            logger.error(f"Error insertando ML run: {e}")

    async def get_training_data(self, min_samples: int = 2000) -> list[dict]:
        """Obtiene datos de trades cerrados con features para entrenamiento."""
        try:
            result = (
                self.client.table("futures_trades")
                .select("*")
                .eq("status", "CLOSED")
                .not_.is_("ml_features", "null")
                .order("closed_at", desc=True)
                .limit(min_samples * 2)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Error obteniendo datos de entrenamiento: {e}")
            return []

    # ── Data Pruning (Limpieza) ────────────────────────────

    async def prune_old_data(self, days: int = 15) -> dict:
        """
        Elimina datos más antiguos que 'days' días.

        Borra:
        - futures_candles con open_time más viejo que el cutoff
        - futures_signals con created_at más viejo
        - futures_trades CERRADOS con closed_at más viejo
          (los OPEN nunca se borran)

        Returns:
            dict con conteos de filas eliminadas
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        cutoff_ms = int(cutoff.timestamp() * 1000)

        deleted = {"candles": 0, "signals": 0, "trades": 0}

        # ── 1. Candles (usa open_time en milliseconds) ──
        try:
            result = (
                self.client.table("futures_candles")
                .delete()
                .lt("open_time", cutoff_ms)
                .execute()
            )
            deleted["candles"] = len(result.data) if result.data else 0
            logger.info(f"Pruned {deleted['candles']} candles")
        except Exception as e:
            logger.error(f"Error pruning candles: {e}")

        # ── 2. Signals (usa created_at timestamp) ──
        try:
            result = (
                self.client.table("futures_signals")
                .delete()
                .lt("created_at", cutoff_iso)
                .execute()
            )
            deleted["signals"] = len(result.data) if result.data else 0
            logger.info(f"Pruned {deleted['signals']} signals")
        except Exception as e:
            logger.error(f"Error pruning signals: {e}")

        # ── 3. Trades cerrados (nunca borrar OPEN) ──
        try:
            result = (
                self.client.table("futures_trades")
                .delete()
                .eq("status", "CLOSED")
                .lt("closed_at", cutoff_iso)
                .execute()
            )
            deleted["trades"] = len(result.data) if result.data else 0
            logger.info(f"Pruned {deleted['trades']} closed trades")
        except Exception as e:
            logger.error(f"Error pruning trades: {e}")

        return deleted


# Instancia global
db = SupabaseClient()
