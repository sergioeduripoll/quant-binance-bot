"""
Generador de señales de trading.
Combina indicadores técnicos para generar señales LONG/SHORT
con nivel de confianza para scalping.
"""

from dataclasses import dataclass
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Signal:
    """Señal de trading generada."""
    symbol: str
    signal_type: str      # 'LONG', 'SHORT', 'NEUTRAL'
    confidence: float     # 0.0 a 1.0
    entry_price: float
    suggested_sl: float
    suggested_tp: float
    suggested_leverage: int
    indicators: dict      # Snapshot de indicadores usados
    reasons: list[str]    # Razones de la señal


class SignalGenerator:
    """
    Genera señales de scalping basadas en confluencia de indicadores.
    
    Criterios de entrada LONG:
    - RSI entre 30-45 (saliendo de sobreventa, no extremo)
    - EMA 9 cruzando por encima de EMA 21
    - MACD cruzando por encima de señal
    - Precio cerca de banda inferior de Bollinger
    - Volumen por encima del promedio (confirmación)
    - Stochastic RSI %K cruzando %D al alza
    
    Criterios de entrada SHORT:
    - RSI entre 55-70 (entrando en sobrecompra)
    - EMA 9 cruzando por debajo de EMA 21
    - MACD cruzando por debajo de señal
    - Precio cerca de banda superior de Bollinger
    - Volumen por encima del promedio
    - Stochastic RSI %K cruzando %D a la baja
    """

    # Pesos de cada criterio (suman ~1.0)
    WEIGHTS = {
        "rsi_zone": 0.15,
        "ema_cross": 0.20,
        "macd_cross": 0.15,
        "bb_position": 0.10,
        "volume_confirm": 0.15,
        "stoch_rsi": 0.10,
        "trend_alignment": 0.15,
    }

    # ── FIX: Bajado de 0.55 a 0.40 ──
    # El backtest mostró que 0.40 es el umbral óptimo para generar
    # suficientes trades sin sacrificar calidad. El ML refinará después.
    def __init__(self, min_confidence: float = 0.40):
        self.min_confidence = min_confidence

    def generate(
        self,
        symbol: str,
        indicators: dict,
        pair_config: dict,
    ) -> Signal:
        """Genera señal basada en los indicadores calculados."""
        if not indicators or indicators.get("rsi_14") is None:
            return self._neutral_signal(symbol, indicators)

        long_score = 0.0
        short_score = 0.0
        reasons_long = []
        reasons_short = []
        price = indicators["price"]

        # ── 1. RSI Zone ──
        rsi = indicators["rsi_14"]
        if 25 <= rsi <= 40:
            long_score += self.WEIGHTS["rsi_zone"]
            reasons_long.append(f"RSI={rsi:.1f} zona de recuperación")
        elif 60 <= rsi <= 75:
            short_score += self.WEIGHTS["rsi_zone"]
            reasons_short.append(f"RSI={rsi:.1f} zona de agotamiento")
        elif rsi < 25:
            long_score += self.WEIGHTS["rsi_zone"] * 0.5
            reasons_long.append(f"RSI={rsi:.1f} sobreventa extrema")
        elif rsi > 75:
            short_score += self.WEIGHTS["rsi_zone"] * 0.5
            reasons_short.append(f"RSI={rsi:.1f} sobrecompra extrema")

        # ── 2. EMA Cross ──
        ema9 = indicators.get("ema_9")
        ema21 = indicators.get("ema_21")
        ema9_prev = indicators.get("ema_9_prev")
        ema21_prev = indicators.get("ema_21_prev")

        if all(v is not None for v in [ema9, ema21, ema9_prev, ema21_prev]):
            # Cruce alcista
            if ema9_prev <= ema21_prev and ema9 > ema21:
                long_score += self.WEIGHTS["ema_cross"]
                reasons_long.append("EMA 9 cruzó encima de EMA 21")
            # Cruce bajista
            elif ema9_prev >= ema21_prev and ema9 < ema21:
                short_score += self.WEIGHTS["ema_cross"]
                reasons_short.append("EMA 9 cruzó debajo de EMA 21")
            # Tendencia existente
            elif ema9 > ema21:
                long_score += self.WEIGHTS["ema_cross"] * 0.4
                reasons_long.append("EMA 9 > EMA 21 (tendencia alcista)")
            elif ema9 < ema21:
                short_score += self.WEIGHTS["ema_cross"] * 0.4
                reasons_short.append("EMA 9 < EMA 21 (tendencia bajista)")

        # ── 3. MACD Cross ──
        macd_val = indicators.get("macd")
        macd_sig = indicators.get("macd_signal")
        macd_prev = indicators.get("macd_prev")
        macd_sig_prev = indicators.get("macd_signal_prev")

        if all(v is not None for v in [macd_val, macd_sig, macd_prev, macd_sig_prev]):
            if macd_prev <= macd_sig_prev and macd_val > macd_sig:
                long_score += self.WEIGHTS["macd_cross"]
                reasons_long.append("MACD cruzó por encima de señal")
            elif macd_prev >= macd_sig_prev and macd_val < macd_sig:
                short_score += self.WEIGHTS["macd_cross"]
                reasons_short.append("MACD cruzó por debajo de señal")

        # ── 4. Bollinger Band Position ──
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        bb_mid = indicators.get("bb_mid")

        if all(v is not None for v in [bb_upper, bb_lower, bb_mid]):
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_pos = (price - bb_lower) / bb_range
                if bb_pos <= 0.2:
                    long_score += self.WEIGHTS["bb_position"]
                    reasons_long.append(f"Precio cerca de BB inferior ({bb_pos:.2f})")
                elif bb_pos >= 0.8:
                    short_score += self.WEIGHTS["bb_position"]
                    reasons_short.append(f"Precio cerca de BB superior ({bb_pos:.2f})")

        # ── 5. Volume Confirmation ──
        vol_ratio = indicators.get("volume_ratio")
        if vol_ratio is not None and vol_ratio > 1.2:
            # Volumen alto confirma la dirección dominante
            weight = self.WEIGHTS["volume_confirm"]
            if long_score > short_score:
                long_score += weight
                reasons_long.append(f"Volumen confirma ({vol_ratio:.1f}x)")
            elif short_score > long_score:
                short_score += weight
                reasons_short.append(f"Volumen confirma ({vol_ratio:.1f}x)")

        # ── 6. Stochastic RSI ──
        stoch_k = indicators.get("stoch_k")
        stoch_d = indicators.get("stoch_d")
        if stoch_k is not None and stoch_d is not None:
            if stoch_k < 20 and stoch_k > stoch_d:
                long_score += self.WEIGHTS["stoch_rsi"]
                reasons_long.append(f"StochRSI %K={stoch_k:.0f} cruzando al alza")
            elif stoch_k > 80 and stoch_k < stoch_d:
                short_score += self.WEIGHTS["stoch_rsi"]
                reasons_short.append(f"StochRSI %K={stoch_k:.0f} cruzando a la baja")

        # ── 7. Trend Alignment (EMA + VWAP) ──
        vwap_val = indicators.get("vwap")
        if vwap_val is not None and ema21 is not None:
            if price > vwap_val and price > ema21:
                long_score += self.WEIGHTS["trend_alignment"]
                reasons_long.append("Precio > VWAP y EMA 21")
            elif price < vwap_val and price < ema21:
                short_score += self.WEIGHTS["trend_alignment"]
                reasons_short.append("Precio < VWAP y EMA 21")

        # ── Determinar señal final ──
        atr_val = indicators.get("atr_14", price * 0.002)
        if atr_val is None or atr_val == 0:
            atr_val = price * 0.002

        if long_score >= self.min_confidence and long_score > short_score:
            sl = price - (atr_val * 1.5)
            tp = price + (atr_val * 2.0)
            lev = self._suggest_leverage(long_score, pair_config)
            return Signal(
                symbol=symbol,
                signal_type="LONG",
                confidence=min(long_score, 1.0),
                entry_price=price,
                suggested_sl=sl,
                suggested_tp=tp,
                suggested_leverage=lev,
                indicators=indicators,
                reasons=reasons_long,
            )

        elif short_score >= self.min_confidence and short_score > long_score:
            sl = price + (atr_val * 1.5)
            tp = price - (atr_val * 2.0)
            lev = self._suggest_leverage(short_score, pair_config)
            return Signal(
                symbol=symbol,
                signal_type="SHORT",
                confidence=min(short_score, 1.0),
                entry_price=price,
                suggested_sl=sl,
                suggested_tp=tp,
                suggested_leverage=lev,
                indicators=indicators,
                reasons=reasons_short,
            )

        return self._neutral_signal(symbol, indicators)

    def _suggest_leverage(self, confidence: float, pair_config: dict) -> int:
        """Sugiere apalancamiento basado en confianza."""
        max_lev = pair_config.get("max_leverage", 20)
        preferred = pair_config.get("preferred_leverage", 10)

        if confidence >= 0.80:
            return min(preferred, max_lev)
        elif confidence >= 0.65:
            return min(int(preferred * 0.7), max_lev)
        else:
            return min(int(preferred * 0.5), max_lev)

    def _neutral_signal(self, symbol: str, indicators: dict) -> Signal:
        """Retorna señal neutral (no operar)."""
        price = indicators.get("price", 0)
        return Signal(
            symbol=symbol,
            signal_type="NEUTRAL",
            confidence=0.0,
            entry_price=price,
            suggested_sl=0,
            suggested_tp=0,
            suggested_leverage=0,
            indicators=indicators,
            reasons=["Sin confluencia suficiente"],
        )
