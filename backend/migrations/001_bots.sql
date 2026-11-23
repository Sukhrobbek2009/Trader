-- Bot tables. Idempotent; run with: python migrate.py
CREATE TABLE IF NOT EXISTS bots (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR NOT NULL,
    status          VARCHAR NOT NULL DEFAULT 'stopped',
    risk_pct        NUMERIC(6,2) NOT NULL DEFAULT 2.5,
    stop_loss_pct   NUMERIC(6,2) NOT NULL DEFAULT 5,
    take_profit_pct NUMERIC(6,2) NOT NULL DEFAULT 10,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bots_status CHECK (status IN ('running', 'stopped'))
);
CREATE INDEX IF NOT EXISTS ix_bots_user ON bots (user_id);

CREATE TABLE IF NOT EXISTS bot_positions (
    bot_id    INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    coin_id   VARCHAR NOT NULL,
    quantity  NUMERIC(28,12) NOT NULL,
    avg_cost  NUMERIC(28,12) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, coin_id)
);

CREATE TABLE IF NOT EXISTS bot_trades (
    id         SERIAL PRIMARY KEY,
    bot_id     INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    coin_id    VARCHAR NOT NULL,
    side       VARCHAR NOT NULL,
    quantity   NUMERIC(28,12) NOT NULL,
    price      NUMERIC(28,12) NOT NULL,
    total      NUMERIC(18,2) NOT NULL,
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bot_trades_side CHECK (side IN ('buy', 'sell'))
);
CREATE INDEX IF NOT EXISTS ix_bot_trades_bot_created ON bot_trades (bot_id, created_at);

CREATE TABLE IF NOT EXISTS bot_equity (
    id         SERIAL PRIMARY KEY,
    bot_id     INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    equity     NUMERIC(18,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_bot_equity_bot_created ON bot_equity (bot_id, created_at);
