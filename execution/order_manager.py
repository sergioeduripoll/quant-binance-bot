"""
Gestor de órdenes en Binance Futures.
Ejecuta market/limit orders con manejo de errores robusto.
"""

import asyncio
import hashlib
import hmac
import time
from urllib.parse import urlencode
from typing import Optional

import aiohttp

from config.settings import (
    BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_REST_BASE, BOT_MODE, BotMode
)
from utils.logger import get_logger
from utils.helpers import current_timestamp_ms

logger = get_logger(__name__)


class OrderManager:
    """Ejecuta y gestiona órdenes en Binance Futures."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._recv_window = 5000

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": BINANCE_API_KEY}
            )
        return self._session

    def _sign(self, params: dict) -> str:
        """Firma HMAC SHA256 para Binance."""
        query = urlencode(params)
        signature = hmac.new(
            BINANCE_API_SECRET.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        signed: bool = True,
    ) -> dict:
        """Ejecuta request autenticado a Binance."""
        if params is None:
            params = {}

        if signed:
            params["timestamp"] = current_timestamp_ms()
            params["recvWindow"] = self._recv_window
            params["signature"] = self._sign(params)

        url = f"{BINANCE_REST_BASE}{endpoint}"
        session = await self._get_session()

        try:
            if method == "GET":
                resp = await session.get(url, params=params)
            elif method == "POST":
                resp = await session.post(url, params=params)
            elif method == "DELETE":
                resp = await session.delete(url, params=params)
            else:
                raise ValueError(f"Method not supported: {method}")

            data = await resp.json()

            if resp.status != 200:
                logger.error(f"Binance API error {resp.status}: {data}")
                return {"error": True, "code": data.get("code"), "msg": data.get("msg")}

            return data

        except Exception as e:
            logger.error(f"Request error {endpoint}: {e}")
            return {"error": True, "msg": str(e)}

    # ── Información de cuenta ──────────────────────────────

    async def get_account_info(self) -> dict:
        """Obtiene información de la cuenta de futuros."""
        return await self._request("GET", "/fapi/v2/account")

    async def get_balance(self) -> float:
        """Obtiene balance disponible en USDT."""
        data = await self._request("GET", "/fapi/v2/balance")
        if isinstance(data, list):
            for asset in data:
                if asset.get("asset") == "USDT":
                    return float(asset.get("availableBalance", 0))
        return 0.0

    async def get_positions(self) -> list[dict]:
        """Obtiene posiciones abiertas."""
        data = await self._request("GET", "/fapi/v2/positionRisk")
        if isinstance(data, list):
            return [
                p for p in data
                if float(p.get("positionAmt", 0)) != 0
            ]
        return []

    # ── Configuración de par ──────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Configura el apalancamiento de un par."""
        return await self._request("POST", "/fapi/v1/leverage", {
            "symbol": symbol,
            "leverage": leverage,
        })

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> dict:
        """Configura el tipo de margen (ISOLATED/CROSSED)."""
        try:
            return await self._request("POST", "/fapi/v1/marginType", {
                "symbol": symbol,
                "marginType": margin_type,
            })
        except Exception:
            # Ya puede estar configurado
            return {"msg": "No need to change margin type."}

    # ── Órdenes ────────────────────────────────────────────

    async def market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict:
        """
        Ejecuta orden de mercado.
        side: 'BUY' (long) o 'SELL' (short)
        """
        if BOT_MODE != BotMode.LIVE:
            logger.info(
                f"[{BOT_MODE.value}] SIMULATED market {side} {quantity} {symbol}"
            )
            return {
                "orderId": f"SIM_{int(time.time()*1000)}",
                "status": "FILLED",
                "avgPrice": "0",
                "executedQty": str(quantity),
                "simulated": True,
            }

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }

        result = await self._request("POST", "/fapi/v1/order", params)
        logger.info(f"Market order {side} {quantity} {symbol}: {result.get('orderId', 'ERROR')}")
        return result

    async def limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
    ) -> dict:
        """Ejecuta orden limit."""
        if BOT_MODE != BotMode.LIVE:
            logger.info(
                f"[{BOT_MODE.value}] SIMULATED limit {side} {quantity} {symbol} @ {price}"
            )
            return {
                "orderId": f"SIM_{int(time.time()*1000)}",
                "status": "NEW",
                "price": str(price),
                "origQty": str(quantity),
                "simulated": True,
            }

        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": time_in_force,
        }

        result = await self._request("POST", "/fapi/v1/order", params)
        logger.info(f"Limit order {side} {quantity} {symbol} @ {price}: {result.get('orderId')}")
        return result

    async def stop_loss_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
    ) -> dict:
        """Coloca Stop Loss (stop market)."""
        if BOT_MODE != BotMode.LIVE:
            logger.info(
                f"[{BOT_MODE.value}] SIMULATED SL {side} {quantity} {symbol} @ {stop_price}"
            )
            return {
                "orderId": f"SIM_SL_{int(time.time()*1000)}",
                "status": "NEW",
                "stopPrice": str(stop_price),
                "simulated": True,
            }

        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
            "closePosition": "false",
        }

        result = await self._request("POST", "/fapi/v1/order", params)
        logger.info(f"SL order {side} {symbol} @ {stop_price}: {result.get('orderId')}")
        return result

    async def take_profit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
    ) -> dict:
        """Coloca Take Profit (take profit market)."""
        if BOT_MODE != BotMode.LIVE:
            logger.info(
                f"[{BOT_MODE.value}] SIMULATED TP {side} {quantity} {symbol} @ {stop_price}"
            )
            return {
                "orderId": f"SIM_TP_{int(time.time()*1000)}",
                "status": "NEW",
                "stopPrice": str(stop_price),
                "simulated": True,
            }

        params = {
            "symbol": symbol,
            "side": side,
            "type": "TAKE_PROFIT_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
            "closePosition": "false",
        }

        result = await self._request("POST", "/fapi/v1/order", params)
        logger.info(f"TP order {side} {symbol} @ {stop_price}: {result.get('orderId')}")
        return result

    async def cancel_all_orders(self, symbol: str) -> dict:
        """Cancela todas las órdenes abiertas de un par."""
        if BOT_MODE != BotMode.LIVE:
            logger.info(f"[{BOT_MODE.value}] SIMULATED cancel all {symbol}")
            return {"code": 200, "msg": "simulated"}

        return await self._request("DELETE", "/fapi/v1/allOpenOrders", {
            "symbol": symbol,
        })

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Cancela una orden específica."""
        if BOT_MODE != BotMode.LIVE:
            return {"msg": "simulated"}

        return await self._request("DELETE", "/fapi/v1/order", {
            "symbol": symbol,
            "orderId": order_id,
        })

    async def get_open_orders(self, symbol: str = None) -> list:
        """Obtiene órdenes abiertas."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        result = await self._request("GET", "/fapi/v1/openOrders", params)
        return result if isinstance(result, list) else []

    # ── Ejecución completa de trade ────────────────────────

    async def open_position(
        self,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int,
        sl_price: float,
        tp_price: float,
        price_precision: int,
    ) -> dict:
        """
        Abre posición completa: leverage + margin + market entry + SL + TP.
        
        Returns dict con order IDs y estado.
        """
        try:
            # 1. Configurar leverage
            await self.set_leverage(symbol, leverage)
            await self.set_margin_type(symbol, "ISOLATED")

            # 2. Entrada market
            buy_side = "BUY" if side == "LONG" else "SELL"
            entry_result = await self.market_order(symbol, buy_side, quantity)

            if entry_result.get("error"):
                return {"success": False, "error": entry_result.get("msg")}

            entry_order_id = entry_result.get("orderId", "")

            # 3. Stop Loss
            sl_side = "SELL" if side == "LONG" else "BUY"
            sl_price_rounded = round(sl_price, price_precision)
            sl_result = await self.stop_loss_order(
                symbol, sl_side, quantity, sl_price_rounded
            )

            # 4. Take Profit
            tp_price_rounded = round(tp_price, price_precision)
            tp_result = await self.take_profit_order(
                symbol, sl_side, quantity, tp_price_rounded
            )

            return {
                "success": True,
                "entry_order_id": entry_order_id,
                "sl_order_id": sl_result.get("orderId", ""),
                "tp_order_id": tp_result.get("orderId", ""),
                "avg_price": float(entry_result.get("avgPrice", 0)),
            }

        except Exception as e:
            logger.error(f"Error abriendo posición {symbol}: {e}")
            return {"success": False, "error": str(e)}

    async def close_position(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict:
        """Cierra posición con market order."""
        try:
            # Cancelar órdenes SL/TP existentes
            await self.cancel_all_orders(symbol)

            # Cerrar con market
            close_side = "SELL" if side == "LONG" else "BUY"
            result = await self.market_order(symbol, close_side, quantity)

            return {
                "success": True,
                "order_id": result.get("orderId", ""),
                "avg_price": float(result.get("avgPrice", 0)),
            }
        except Exception as e:
            logger.error(f"Error cerrando posición {symbol}: {e}")
            return {"success": False, "error": str(e)}

    async def close(self):
        """Cierra la sesión HTTP."""
        if self._session and not self._session.closed:
            await self._session.close()
