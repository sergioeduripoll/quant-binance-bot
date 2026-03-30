"""
Scalping Bot - Binance Futures
Punto de entrada principal.

Uso:
    python main.py              # Inicia el bot
    python main.py --mode TEST  # Override del modo
"""

import asyncio
import signal
import sys
import os

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.engine import Engine
from config.settings import BOT_MODE
from utils.logger import get_logger

logger = get_logger("main")


def parse_args():
    """Parsea argumentos de línea de comandos."""
    import argparse
    parser = argparse.ArgumentParser(description="Scalping Bot - Binance Futures")
    parser.add_argument(
        "--mode",
        choices=["TEST", "PAPER", "LIVE"],
        default=None,
        help="Override del modo de operación",
    )
    return parser.parse_args()


async def main():
    """Función principal async."""
    args = parse_args()

    if args.mode:
        os.environ["BOT_MODE"] = args.mode
        logger.info(f"Mode override: {args.mode}")

    engine = Engine()

    # Manejo de señales para shutdown limpio
    loop = asyncio.get_running_loop()

    def shutdown_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(engine.shutdown())

# for sig in (signal.SIGINT, signal.SIGTERM):
#     loop.add_signal_handler(sig, shutdown_handler)

    logger.info(f"Starting Scalping Bot in {BOT_MODE.value} mode...")
    await engine.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
