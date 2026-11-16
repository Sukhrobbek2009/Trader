---
description: Add a new coin to CoinLab (usage: /add-coin <coingecko-id> <name> <symbol> <hex-color>)
---
Add a coin to the `COINS` array in `index.html` using the arguments: $ARGUMENTS

Format is `[id, name, symbol, color, fallbackPrice, fallbackChange24h]`. The id must be a valid CoinGecko id. Look up a sensible fallback price. Then check whether anything else keys off the coin list (e.g. `META` around the coin page, the `PALETTE` for the allocation chart) and update it so the coin works on the market, coin, portfolio, and history views. Summarize the change.
