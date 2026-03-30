"""
Predictor ML en tiempo real.
Usa el modelo entrenado para evaluar señales de trading.
"""

import asyncio
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from config.settings import ML_MIN_SAMPLES, ML_RETRAIN_INTERVAL_HOURS
from ml.feature_engineer import extract_features, features_to_array
from ml.model_trainer import ModelTrainer
from database.supabase_client import db
from notifications.telegram_notifier import TelegramNotifier
from utils.logger import get_logger

logger = get_logger(__name__)


class Predictor:
    """
    Predictor en tiempo real que se auto-actualiza.
    
    Flujo:
    1. Recibe indicadores técnicos
    2. Extrae features
    3. Ejecuta modelo ML
    4. Retorna probabilidad de trade rentable
    5. Se re-entrena periódicamente
    """

    def __init__(self):
        self.trainer = ModelTrainer()
        self.notifier = TelegramNotifier()
        self._last_train_time: Optional[datetime] = None
        self._is_training = False
        self._ready = False

    async def initialize(self):
        """Inicializa el predictor: carga modelo o entrena si hay datos."""
        # Intentar cargar modelo guardado
        if self.trainer.load_model():
            self._ready = True
            logger.info("Predictor inicializado con modelo guardado")
            return

        # Intentar entrenar con datos existentes
        await self._try_train()

    async def predict(self, indicators: dict) -> Optional[float]:
        """
        Predice probabilidad de trade rentable.
        
        Args:
            indicators: dict con indicadores técnicos
        
        Returns:
            float entre 0 y 1, o None si modelo no disponible
        """
        if not self._ready or self.trainer.model is None:
            return None

        features = extract_features(indicators)
        if features is None:
            return None

        try:
            X = features_to_array(features).reshape(1, -1)
            proba = self.trainer.model.predict_proba(X)[0]
            # proba[1] = probabilidad de ser rentable
            confidence = float(proba[1])
            return confidence
        except Exception as e:
            logger.error(f"Error en predicción ML: {e}")
            return None

    async def maybe_retrain(self):
        """Verifica si es momento de re-entrenar y lo hace si corresponde."""
        if self._is_training:
            return

        now = datetime.now(timezone.utc)

        # Verificar intervalo de re-entrenamiento
        if self._last_train_time:
            hours_since = (now - self._last_train_time).total_seconds() / 3600
            if hours_since < ML_RETRAIN_INTERVAL_HOURS:
                return

        await self._try_train()

    async def _try_train(self):
        """Intenta entrenar el modelo."""
        self._is_training = True
        try:
            # Verificar si hay suficientes muestras
            bot_state = await db.get_bot_state()
            samples = int(bot_state.get("samples_collected", 0)) if bot_state else 0

            if samples < ML_MIN_SAMPLES:
                logger.info(
                    f"ML: {samples}/{ML_MIN_SAMPLES} muestras. "
                    f"Faltan {ML_MIN_SAMPLES - samples}."
                )
                return

            logger.info("Iniciando entrenamiento ML...")
            metrics = await self.trainer.train()

            if metrics:
                self._ready = True
                self._last_train_time = datetime.now(timezone.utc)

                await self.notifier.notify_ml_trained(
                    accuracy=metrics["accuracy"],
                    samples=metrics["samples_used"],
                    version=metrics["model_version"],
                )

                logger.info(
                    f"ML entrenado: accuracy={metrics['accuracy']:.3f}"
                )
            else:
                logger.warning("Entrenamiento ML retornó None")

        except Exception as e:
            logger.error(f"Error en entrenamiento ML: {e}")
        finally:
            self._is_training = False

    @property
    def is_ready(self) -> bool:
        return self._ready
