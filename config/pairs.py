"""
Configuración de pares de trading.
Define los pares, sus parámetros específicos y filtros de volumen.
"""

# Pares activos para scalping en Futuros
# Ajusta según tu análisis y preferencia
TRADING_PAIRS = [
    {
        "symbol": "BTCUSDT",
        "min_volume_24h": 500_000_000,   # Volumen mínimo 24h en USDT
        "tick_size": 0.10,               # Mínimo movimiento de precio
        "qty_precision": 3,              # Decimales en cantidad
        "price_precision": 2,            # Decimales en precio
        "max_leverage": 20,
        "preferred_leverage": 10,
    },
    {
        "symbol": "ETHUSDT",
        "min_volume_24h": 200_000_000,
        "tick_size": 0.01,
        "qty_precision": 3,
        "price_precision": 2,
        "max_leverage": 20,
        "preferred_leverage": 10,
    },
    {
        "symbol": "SOLUSDT",
        "min_volume_24h": 100_000_000,
        "tick_size": 0.010,
        "qty_precision": 0,
        "price_precision": 3,
        "max_leverage": 15,
        "preferred_leverage": 8,
    },
    {
        "symbol": "BNBUSDT",
        "min_volume_24h": 50_000_000,
        "tick_size": 0.01,
        "qty_precision": 2,
        "price_precision": 2,
        "max_leverage": 15,
        "preferred_leverage": 8,
    },
    {
        "symbol": "XRPUSDT",
        "min_volume_24h": 80_000_000,
        "tick_size": 0.0001,
        "qty_precision": 1,
        "price_precision": 4,
        "max_leverage": 15,
        "preferred_leverage": 8,
    },
]


def get_pair_config(symbol: str) -> dict | None:
    """Obtiene la configuración de un par específico."""
    for pair in TRADING_PAIRS:
        if pair["symbol"] == symbol:
            return pair
    return None


def get_all_symbols() -> list[str]:
    """Retorna lista de todos los símbolos activos."""
    return [p["symbol"] for p in TRADING_PAIRS]
