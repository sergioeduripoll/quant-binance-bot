"""
Entrenador de modelo ML para predicción de trades rentables.
Usa LightGBM por su velocidad y rendimiento con datos tabulares.
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import joblib
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from config.settings import ML_MIN_SAMPLES, ML_MODEL_PATH
from database.supabase_client import db
from ml.feature_engineer import (
    extract_features, features_to_array, create_label, FEATURE_COLUMNS
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ModelTrainer:
    """
    Entrena y evalúa modelo de clasificación para filtrar trades.
    
    El modelo predice la probabilidad de que un trade sea rentable
    dado un set de features técnicos.
    """

    def __init__(self):
        self.model = None
        self.version = None
        self.last_accuracy = 0.0

    async def train(self) -> dict | None:
        """
        Entrena el modelo con datos históricos de Supabase.
        
        Returns:
            dict con métricas o None si no hay suficientes datos
        """
        # ── 1. Obtener datos ──
        trades = await db.get_training_data(ML_MIN_SAMPLES)
        if len(trades) < ML_MIN_SAMPLES:
            logger.info(
                f"Datos insuficientes para ML: {len(trades)}/{ML_MIN_SAMPLES}"
            )
            return None

        # ── 2. Preparar features y labels ──
        X_list = []
        y_list = []

        for trade in trades:
            ml_features = trade.get("ml_features")
            if not ml_features:
                continue

            features = extract_features(ml_features)
            if features is None:
                continue

            X_list.append(features_to_array(features))
            y_list.append(create_label(trade))

        if len(X_list) < ML_MIN_SAMPLES * 0.8:
            logger.warning(f"Features extraíbles insuficientes: {len(X_list)}")
            return None

        X = np.array(X_list)
        y = np.array(y_list)

        logger.info(
            f"Training data: {len(X)} samples, "
            f"{sum(y)} wins ({sum(y)/len(y):.1%}), "
            f"{len(y) - sum(y)} losses"
        )

        # ── 3. Entrenar con validación temporal ──
        try:
            import lightgbm as lgb
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            logger.warning("LightGBM no disponible, usando sklearn GBM")
            return await self._train_sklearn(X, y)

        return await self._train_lightgbm(X, y)

    async def _train_lightgbm(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Entrena con LightGBM."""
        import lightgbm as lgb

        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
            "n_estimators": 200,
            "min_child_samples": 20,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
        }

        # Time series split (no random para preservar orden temporal)
        tscv = TimeSeriesSplit(n_splits=5)
        accuracies = []
        precisions = []
        recalls = []
        f1s = []

        for train_idx, val_idx in tscv.split(X):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            model = lgb.LGBMClassifier(**params)
            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
            )

            y_pred = model.predict(X_val)
            accuracies.append(accuracy_score(y_val, y_pred))
            precisions.append(precision_score(y_val, y_pred, zero_division=0))
            recalls.append(recall_score(y_val, y_pred, zero_division=0))
            f1s.append(f1_score(y_val, y_pred, zero_division=0))

        # Entrenar modelo final con todos los datos
        final_model = lgb.LGBMClassifier(**params)
        final_model.fit(X, y)

        self.model = final_model
        self.version = f"lgbm_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
        self.last_accuracy = np.mean(accuracies)

        # Guardar modelo
        os.makedirs(os.path.dirname(ML_MODEL_PATH), exist_ok=True)
        joblib.dump(final_model, ML_MODEL_PATH)

        metrics = {
            "model_version": self.version,
            "samples_used": len(X),
            "accuracy": float(np.mean(accuracies)),
            "precision_score": float(np.mean(precisions)),
            "recall_score": float(np.mean(recalls)),
            "f1_score": float(np.mean(f1s)),
            "hyperparams": params,
            "features_used": FEATURE_COLUMNS,
        }

        # Registrar en Supabase
        await db.insert_ml_run(metrics)
        await db.update_bot_state({
            "ml_model_version": self.version,
            "ml_accuracy": metrics["accuracy"],
            "ml_last_trained": datetime.now(timezone.utc).isoformat(),
        })

        # Feature importance
        importances = dict(zip(FEATURE_COLUMNS, final_model.feature_importances_))
        top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]
        logger.info(f"Top features: {top_features}")

        logger.info(
            f"ML trained: v={self.version} acc={metrics['accuracy']:.3f} "
            f"prec={metrics['precision_score']:.3f} f1={metrics['f1_score']:.3f}"
        )

        return metrics

    async def _train_sklearn(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Fallback: entrena con sklearn GradientBoosting."""
        from sklearn.ensemble import GradientBoostingClassifier

        params = {
            "n_estimators": 150,
            "max_depth": 5,
            "learning_rate": 0.05,
            "min_samples_leaf": 20,
            "subsample": 0.8,
        }

        tscv = TimeSeriesSplit(n_splits=5)
        accuracies = []

        for train_idx, val_idx in tscv.split(X):
            model = GradientBoostingClassifier(**params)
            model.fit(X[train_idx], y[train_idx])
            y_pred = model.predict(X[val_idx])
            accuracies.append(accuracy_score(y[val_idx], y_pred))

        final_model = GradientBoostingClassifier(**params)
        final_model.fit(X, y)

        self.model = final_model
        self.version = f"sklearn_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
        self.last_accuracy = np.mean(accuracies)

        os.makedirs(os.path.dirname(ML_MODEL_PATH), exist_ok=True)
        joblib.dump(final_model, ML_MODEL_PATH)

        metrics = {
            "model_version": self.version,
            "samples_used": len(X),
            "accuracy": float(np.mean(accuracies)),
            "precision_score": 0,
            "recall_score": 0,
            "f1_score": 0,
            "hyperparams": params,
            "features_used": FEATURE_COLUMNS,
        }

        await db.insert_ml_run(metrics)
        logger.info(f"sklearn trained: acc={np.mean(accuracies):.3f}")
        return metrics

    def load_model(self) -> bool:
        """Carga modelo guardado del disco."""
        if os.path.exists(ML_MODEL_PATH):
            try:
                self.model = joblib.load(ML_MODEL_PATH)
                logger.info(f"Modelo ML cargado: {ML_MODEL_PATH}")
                return True
            except Exception as e:
                logger.error(f"Error cargando modelo: {e}")
        return False
