-- ============================================================
-- SCALPING BOT - SUPABASE DATABASE SETUP
-- Ejecutar en Supabase SQL Editor
-- Prefijo futures_ para no colisionar con el bot anterior
-- ============================================================

-- ── Tabla de trades (registro completo de operaciones) ────
CREATE TABLE IF NOT EXISTS futures_trades (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    
    -- Identificación
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    
    -- Entrada
    entry_price     NUMERIC(20, 8) NOT NULL,
    quantity        NUMERIC(20, 8) NOT NULL,
    leverage        INTEGER NOT NULL DEFAULT 1,
    notional_value  NUMERIC(20, 4),
    
    -- Salida
    exit_price      NUMERIC(20, 8),
    exit_reason     TEXT CHECK (exit_reason IN ('TP', 'SL', 'TRAILING_SL', 'MANUAL', 'LIQUIDATION', NULL)),
    
    -- P&L
    pnl_gross       NUMERIC(20, 8) DEFAULT 0,
    commission_paid NUMERIC(20, 8) DEFAULT 0,
    pnl_net         NUMERIC(20, 8) DEFAULT 0,
    pnl_percentage  NUMERIC(10, 4) DEFAULT 0,
    
    -- Risk
    initial_sl      NUMERIC(20, 8),
    initial_tp      NUMERIC(20, 8),
    final_sl        NUMERIC(20, 8),
    final_tp        NUMERIC(20, 8),
    risk_reward     NUMERIC(10, 4),
    
    -- Estado
    status          TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
    
    -- ML
    signal_confidence NUMERIC(6, 4),
    ml_features     JSONB,
    
    -- Binance IDs
    entry_order_id  TEXT,
    exit_order_id   TEXT
);

-- Índices para consultas rápidas
CREATE INDEX IF NOT EXISTS idx_ft_symbol ON futures_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_ft_status ON futures_trades(status);
CREATE INDEX IF NOT EXISTS idx_ft_created ON futures_trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ft_symbol_status ON futures_trades(symbol, status);


-- ── Tabla de velas procesadas (para ML) ───────────────────
CREATE TABLE IF NOT EXISTS futures_candles (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    symbol          TEXT NOT NULL,
    interval        TEXT NOT NULL DEFAULT '5m',
    open_time       BIGINT NOT NULL,
    close_time      BIGINT NOT NULL,
    open            NUMERIC(20, 8) NOT NULL,
    high            NUMERIC(20, 8) NOT NULL,
    low             NUMERIC(20, 8) NOT NULL,
    close           NUMERIC(20, 8) NOT NULL,
    volume          NUMERIC(20, 4) NOT NULL,
    quote_volume    NUMERIC(20, 4),
    trades_count    INTEGER,
    taker_buy_vol   NUMERIC(20, 4),
    
    -- Indicadores pre-calculados
    rsi_14          NUMERIC(10, 4),
    ema_9           NUMERIC(20, 8),
    ema_21          NUMERIC(20, 8),
    vwap            NUMERIC(20, 8),
    atr_14          NUMERIC(20, 8),
    volume_sma_20   NUMERIC(20, 4),
    bb_upper        NUMERIC(20, 8),
    bb_lower        NUMERIC(20, 8),
    macd            NUMERIC(20, 8),
    macd_signal     NUMERIC(20, 8),
    
    UNIQUE(symbol, open_time)
);

CREATE INDEX IF NOT EXISTS idx_fc_symbol_time ON futures_candles(symbol, open_time DESC);


-- ── Tabla de señales generadas ────────────────────────────
CREATE TABLE IF NOT EXISTS futures_signals (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    signal_type     TEXT NOT NULL CHECK (signal_type IN ('LONG', 'SHORT', 'NEUTRAL')),
    confidence      NUMERIC(6, 4) NOT NULL,
    entry_price     NUMERIC(20, 8),
    suggested_sl    NUMERIC(20, 8),
    suggested_tp    NUMERIC(20, 8),
    suggested_lev   INTEGER,
    indicators      JSONB,
    was_executed     BOOLEAN DEFAULT FALSE,
    trade_id        UUID REFERENCES futures_trades(id)
);

CREATE INDEX IF NOT EXISTS idx_fs_symbol ON futures_signals(symbol, created_at DESC);


-- ── Estado del bot y métricas ─────────────────────────────
CREATE TABLE IF NOT EXISTS futures_bot_state (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    
    -- Capital
    total_balance   NUMERIC(20, 4),
    available_balance NUMERIC(20, 4),
    unrealized_pnl  NUMERIC(20, 4),
    
    -- Métricas del día
    daily_pnl       NUMERIC(20, 4) DEFAULT 0,
    daily_trades    INTEGER DEFAULT 0,
    daily_wins      INTEGER DEFAULT 0,
    daily_losses    INTEGER DEFAULT 0,
    
    -- Métricas globales
    total_trades    INTEGER DEFAULT 0,
    total_wins      INTEGER DEFAULT 0,
    total_losses    INTEGER DEFAULT 0,
    win_rate        NUMERIC(6, 4) DEFAULT 0,
    avg_win         NUMERIC(20, 8) DEFAULT 0,
    avg_loss        NUMERIC(20, 8) DEFAULT 0,
    profit_factor   NUMERIC(10, 4) DEFAULT 0,
    max_drawdown    NUMERIC(10, 4) DEFAULT 0,
    
    -- ML
    ml_model_version TEXT,
    ml_accuracy     NUMERIC(6, 4),
    ml_last_trained TIMESTAMPTZ,
    samples_collected INTEGER DEFAULT 0
);

-- Insertar estado inicial
INSERT INTO futures_bot_state (total_balance, available_balance)
VALUES (0, 0)
ON CONFLICT DO NOTHING;


-- ── Tabla de trailing stop history ────────────────────────
CREATE TABLE IF NOT EXISTS futures_trailing_history (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    trade_id        UUID REFERENCES futures_trades(id),
    symbol          TEXT NOT NULL,
    old_sl          NUMERIC(20, 8),
    new_sl          NUMERIC(20, 8),
    old_tp          NUMERIC(20, 8),
    new_tp          NUMERIC(20, 8),
    current_price   NUMERIC(20, 8),
    current_pnl     NUMERIC(20, 8),
    reason          TEXT
);

CREATE INDEX IF NOT EXISTS idx_fth_trade ON futures_trailing_history(trade_id);


-- ── Tabla de ML training runs ─────────────────────────────
CREATE TABLE IF NOT EXISTS futures_ml_runs (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    model_version   TEXT NOT NULL,
    samples_used    INTEGER,
    features_used   JSONB,
    accuracy        NUMERIC(6, 4),
    precision_score NUMERIC(6, 4),
    recall_score    NUMERIC(6, 4),
    f1_score        NUMERIC(6, 4),
    hyperparams     JSONB,
    notes           TEXT
);


-- ── Función para actualizar métricas automáticamente ──────
CREATE OR REPLACE FUNCTION update_bot_metrics()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'CLOSED' AND OLD.status = 'OPEN' THEN
        UPDATE futures_bot_state
        SET 
            total_trades = total_trades + 1,
            total_wins = total_wins + CASE WHEN NEW.pnl_net > 0 THEN 1 ELSE 0 END,
            total_losses = total_losses + CASE WHEN NEW.pnl_net <= 0 THEN 1 ELSE 0 END,
            daily_trades = daily_trades + 1,
            daily_wins = daily_wins + CASE WHEN NEW.pnl_net > 0 THEN 1 ELSE 0 END,
            daily_losses = daily_losses + CASE WHEN NEW.pnl_net <= 0 THEN 1 ELSE 0 END,
            daily_pnl = daily_pnl + COALESCE(NEW.pnl_net, 0),
            samples_collected = samples_collected + 1,
            win_rate = CASE 
                WHEN (total_trades + 1) > 0 
                THEN (total_wins + CASE WHEN NEW.pnl_net > 0 THEN 1 ELSE 0 END)::NUMERIC / (total_trades + 1)
                ELSE 0 
            END,
            updated_at = NOW()
        WHERE id = (SELECT id FROM futures_bot_state LIMIT 1);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_update_metrics
    AFTER UPDATE ON futures_trades
    FOR EACH ROW
    EXECUTE FUNCTION update_bot_metrics();


-- ── Función para resetear métricas diarias (cron) ─────────
CREATE OR REPLACE FUNCTION reset_daily_metrics()
RETURNS void AS $$
BEGIN
    UPDATE futures_bot_state
    SET daily_pnl = 0,
        daily_trades = 0,
        daily_wins = 0,
        daily_losses = 0,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;


-- ── RLS (Row Level Security) ──────────────────────────────
-- Habilitar RLS en todas las tablas
ALTER TABLE futures_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE futures_candles ENABLE ROW LEVEL SECURITY;
ALTER TABLE futures_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE futures_bot_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE futures_trailing_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE futures_ml_runs ENABLE ROW LEVEL SECURITY;

-- Políticas permisivas para service_role (el bot usa service key)
CREATE POLICY "service_all" ON futures_trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON futures_candles FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON futures_signals FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON futures_bot_state FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON futures_trailing_history FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_all" ON futures_ml_runs FOR ALL USING (true) WITH CHECK (true);
