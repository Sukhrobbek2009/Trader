# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Security

Never commit or push keys, tokens, or other sensitive information. Follow @SECURITY.md and keep `.gitignore` up to date.

## Project

"CoinLab" — a crypto practice-trading simulator (real CoinGecko prices, fake $10,000). The whole app is a single static file, `index.html` (~1700 lines: `<style>` at the top, markup, then one inline `<script>`). There is no build, package manager, test suite, or linter. To run it, open `index.html` in a browser (or `python3 -m http.server`); edit and reload.

## Architecture

- **Routing**: hash-based, handled by `route()`. Views are sibling containers toggled via `hidden`: `#viewMarket` (static markup), and `#viewCoin`, `#viewPortfolio`, `#viewHistory`, `#viewReceipt` (filled by `renderCoin`, `renderPortfolio`, `renderHistory`, `renderReceipt`). Routes: `#/`, `#/coin/<id>`, `#/portfolio`, `#/history`, `#/history/<tradeIndex>`. `route()` also manages scroll restoration, focus, and `document.title`.
- **Data**: `COINS` (10 hardcoded coins, with fallback price/24h change) seeds the `state` map (id → price/chg/img/live). `refresh()` polls CoinGecko `/coins/markets` every 30s and then calls `update(prev)`; coins missing from the response get `price: null`, and the UI must handle that ("price unavailable") via `hasPrice`/`dirOf`. Feed failure and offline states are handled distinctly (status pill, offline banner).
- **Charts/sparklines are fake**: `fakeHistory`/`series` generate seeded synthetic data (the code comments say a future backend will supply real history). Charts are hand-rolled SVG (`drawChart`, `drawPfChart`) — no chart library.
- **Trading flow**: `bindTrade` → `orderState` (validation) → `openConfirm`/`renderConfirm` (a `<dialog>` that re-renders on every live price tick so the displayed price is what executes) → `executeOrder`.
- **Persistence**: all state lives in `localStorage` under `coinlab.*` keys (`cash`, `holdings`, `costs`, `trades`, `watchlist`, `theme`, `welcomed`, `traded`). Every access is wrapped in try/catch; keep it that way. `executeOrder` writes cash, holdings, costs and trades together. Comments reference a planned backend ("Lesson 6/7").
- **Rendering style**: vanilla JS, no framework; views are built as HTML strings (escape user/remote text with `esc`) and assigned to `innerHTML`. Formatting helpers: `fmtUSD`, `fmtCash`, `fmtPct`, `sign`.
- **Theming**: CSS variables; a tiny inline script in `<head>` applies the saved theme before first paint, and `data-theme` on `<html>` overrides `prefers-color-scheme`.
- **Accessibility/motion**: the code deliberately honors `prefers-reduced-motion` (the `reduceMotion` flag gates `tween`, confetti, chart draw-ins) and uses ARIA roles, `aria-live` regions, and managed focus on route changes. Preserve these when adding UI.
