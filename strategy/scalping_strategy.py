"""
Estrategia principal de scalping.
Orquesta indicadores, señales y validación de riesgo.
"""

from strategy.indicators import calculate_all_indicators
from strategy.signal_generator import SignalGenerator, Signal
from config.pairs import get_pair_config
from utils.logger import get_logger

logger = get_logger(__name__)


class ScalpingStrategy:
    """
    Estrategia de scalping de alta frecuencia.
    
    Flujo:
    1. Recibe velas del CandleProcessor
    2. Calcula indicadores técnicos
    3. Genera señal (LONG/SHORT/NEUTRAL)
    4. Valida con ML predictor (si disponible)
    5. Retorna señal final para ejecución
    """

    # ── FIX: Bajado de 0.55 a 0.40 ──
    def __init__(self, min_confidence: float = 0.40):
        self.signal_gen = SignalGenerator(min_confidence=min_confidence)
        self.ml_predictor = None  # Se inyecta después

    def set_ml_predictor(self, predictor):
        """Inyecta el predictor ML."""
        self.ml_predictor = predictor

    async def analyze(
        self,
        symbol: str,
        current_candle,
        history: list,
    ) -> Signal | None:
        """
        Analiza un símbolo y genera señal.
        Se llama en pre-close (3s antes del cierre de vela).
        """
        pair_config = get_pair_config(symbol)
        if not pair_config:
            logger.warning(f"Par no configurado: {symbol}")
            return None

        # Construir lista completa con la vela actual
        all_candles = history + [current_candle]

        if len(all_candles) < 30:
            logger.debug(f"{symbol}: Insuficientes velas ({len(all_candles)})")
            return None

        # ── Calcular indicadores ──
        indicators = calculate_all_indicators(all_candles)
        if not indicators:
            return None

        # ── Generar señal base ──
        signal = self.signal_gen.generate(symbol, indicators, pair_config)

        if signal.signal_type == "NEUTRAL":
            return signal

        # ── Ajustar con ML si disponible ──
        if self.ml_predictor is not None:
            try:
                ml_confidence = await self.ml_predictor.predict(indicators)
                if ml_confidence is not None:
                    # Blend: 60% técnico + 40% ML
                    blended = signal.confidence * 0.6 + ml_confidence * 0.4
                    signal.confidence = blended
                    signal.reasons.append(
                        f"ML confidence: {ml_confidence:.2f} → blended: {blended:.2f}"
                    )
                    logger.info(
                        f"{symbol} ML adjustment: {ml_confidence:.2f} → {blended:.2f}"
                    )
            except Exception as e:
                logger.warning(f"ML prediction failed for {symbol}: {e}")

        # ── Filtro de confianza final ──
        if signal.confidence < self.signal_gen.min_confidence:
            signal.signal_type = "NEUTRAL"
            signal.reasons.append(
                f"Confianza final {signal.confidence:.2f} < mínimo {self.signal_gen.min_confidence}"
            )

        logger.info(
            f"SIGNAL {symbol}: {signal.signal_type} "
            f"conf={signal.confidence:.2f} | {', '.join(signal.reasons[:3])}"
        )

        return signal
