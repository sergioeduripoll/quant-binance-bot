# Scalping Bot - Binance Futures

Bot autónomo de scalping para Binance Futuros con ML adaptativo, trailing stop inteligente y notificaciones Telegram.

## Arquitectura

```
scalping-bot/
├── config/                  # Configuración global
│   ├── settings.py          # Variables de entorno y constantes
│   └── pairs.py             # Pares de trading configurados
├── core/                    # Motor principal
│   ├── engine.py            # Orquestador del bot
│   ├── websocket_manager.py # Conexión WebSocket a Binance
│   └── candle_processor.py  # Procesamiento de velas y timing
├── strategy/                # Lógica de estrategia
│   ├── scalping_strategy.py # Estrategia principal de scalping
│   ├── indicators.py        # Indicadores técnicos
│   └── signal_generator.py  # Generador de señales (compra/venta)
├── execution/               # Ejecución de órdenes
│   ├── order_manager.py     # Gestión de órdenes en Binance
│   ├── position_manager.py  # Control de posiciones abiertas
│   └── trailing_stop.py     # Trailing stop dinámico
├── risk/                    # Gestión de riesgo
│   ├── position_sizer.py    # Cálculo de tamaño de posición
│   ├── commission_calc.py   # Cálculo de comisiones Binance
│   └── risk_manager.py      # Validación de riesgo pre-trade
├── ml/                      # Machine Learning
│   ├── feature_engineer.py  # Ingeniería de features
│   ├── model_trainer.py     # Entrenamiento del modelo
│   └── predictor.py         # Predicción en tiempo real
├── database/                # Capa de datos
│   ├── supabase_client.py   # Cliente Supabase
│   └── models.py            # Esquemas de tablas
├── notifications/           # Notificaciones
│   └── telegram_notifier.py # Bot de Telegram
├── utils/                   # Utilidades
│   ├── logger.py            # Logging estructurado
│   └── helpers.py           # Funciones auxiliares
├── scripts/                 # Scripts de setup
│   ├── setup_supabase.sql   # SQL para crear tablas
│   └── deploy.sh            # Script de despliegue DO
├── main.py                  # Punto de entrada
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Stack Tecnológico
- **Python 3.11+** con asyncio para concurrencia
- **WebSockets** para datos en tiempo real de Binance
- **Supabase** (PostgreSQL) para persistencia
- **scikit-learn / LightGBM** para ML adaptativo
- **Telegram Bot API** para notificaciones
- **Docker** para despliegue en DigitalOcean

## Despliegue Rápido

```bash
# 1. Clonar y configurar
git clone <tu-repo>
cd scalping-bot
cp .env.example .env
# Editar .env con tus claves

# 2. Crear tablas en Supabase
# Ejecutar scripts/setup_supabase.sql en el SQL Editor de Supabase

# 3. Desplegar con Docker
docker-compose up -d
```

## Modos de Operación
- `TEST`: Recolecta datos y envía notificaciones. No ejecuta trades reales.
- `PAPER`: Simula trades con datos reales. Registra todo en Supabase.
- `LIVE`: Operación autónoma completa con capital real.
