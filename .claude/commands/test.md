---
description: Test CoinLab in a real browser (optionally focus on an area, e.g. /test trading)
allowed-tools: Bash(python3 -m http.server:*), Bash(node --check:*), Bash(git diff:*), Bash(git status:*)
---
This project has no test suite, so verify by running the app. Focus area (optional): $ARGUMENTS

1. Check JS syntax: extract the inline `<script>` from `index.html` and run `node --check` on it (use the scratchpad directory for the temp file).
2. Serve the app with `python3 -m http.server` on a free port and open it in a browser (load the `claude-in-chrome` or built-in browser skill first). Check the console for errors.
3. Exercise the flows, limited to the focus area if one was given, otherwise prioritising whatever `git diff` shows changed:
   - **Market:** list renders, search filters, star/unstar updates the watchlist, status pill shows live prices.
   - **Coin page:** range switch (1D/7D/30D), chart scrub, buy and sell validation (empty, zero, more than cash, more than held), confirm sheet, toast.
   - **Portfolio:** holdings, allocation chart, and totals match cash plus holdings value after a trade.
   - **History:** trade appears, filters work, receipt page `#/history/<n>` opens and back works.
   - **Edge states:** offline (feed failure shows last prices), a coin with no price, first-visit welcome dialog, dark and light theme, reduced motion.
4. Use fresh `localStorage` (clear `coinlab.*` keys) for the first-run checks, and restore or clear it afterwards.
5. Stop the server when done.

Report a short pass/fail list with the exact steps for any failure. Don't fix anything unless I ask.
