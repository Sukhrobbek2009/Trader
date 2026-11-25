-- Each bot trades one coin with one strategy, from its own cash pot.
-- bots is empty at this point, so NOT NULL columns need no backfill.
ALTER TABLE bots ADD COLUMN IF NOT EXISTS coin_id  VARCHAR NOT NULL;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS strategy VARCHAR NOT NULL;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS bot_cash NUMERIC(18,2) NOT NULL DEFAULT 0;
ALTER TABLE bots DROP CONSTRAINT IF EXISTS ck_bots_bot_cash;
ALTER TABLE bots ADD CONSTRAINT ck_bots_bot_cash CHECK (bot_cash >= 0);
