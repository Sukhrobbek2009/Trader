-- Real recent prices for the strategies: one row per refresh per coin,
-- pruned to the newest 500 per coin by app/prices.py. Idempotent.
CREATE TABLE IF NOT EXISTS price_history (
    id      SERIAL PRIMARY KEY,
    coin_id VARCHAR NOT NULL,
    price   NUMERIC(28,12) NOT NULL,
    at      TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_price_history_coin_at ON price_history (coin_id, at);
