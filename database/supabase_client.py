"""
Cliente Supabase centralizado.
Maneja todas las operaciones CRUD con la base de datos.
"""

import asyncio
from datetime import datetime, timezone
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
        except Exception as e:
            logger.error(f"Error insertando trade: {e}")
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
            logger.error(f"Error actualizando trade {trade_id}: {e}")
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
            self.client.table("futures_candles").upsert(
                candle_data, on_conflict="symbol,open_time"
            ).execute()
        except Exception as e:
            logger.error(f"Error insertando vela: {e}")

    async def get_candles(
        self, symbol: str, limit: int = 200
    ) -> list[dict]:
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
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error insertando señal: {e}")
            return None

    # ── Bot State ──────────────────────────────────────────

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


# Instancia global
db = SupabaseClient()
