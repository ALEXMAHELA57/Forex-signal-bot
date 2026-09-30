# Forex Signal Bot

Analyzes **EURUSD, GBPUSD, USDJPY and XAUUSD** on M15 using H1/H4 trend, and posts
**BUY/SELL signals with Entry, Stop Loss and 3 Take Profits** to a Telegram channel.
It then follows every signal and replies when TP1/TP2/TP3 or the SL is hit, and posts
a daily results summary. It **never places trades** — it only reads prices.

```
🟢 BUY XAUUSD  ·  M15
Entry: 2345.60
Stop Loss: 2338.20  (74.0 pips)
TP1: 2353.00  (74.0 pips · 1.0R)
TP2: 2360.40  (148.0 pips · 2.0R)
TP3: 2367.80  (222.0 pips · 3.0R)
Confidence: Strong (85/100)
Why: H4 trend up · H1 trend up · M15 EMAs aligned · MACD momentum rising · pullback to EMA20 · ADX 27
```

## How it decides

Each closed M15 candle is scored 0–100 for BUY and SELL (details in `bot/strategy.py`):

| Points | Condition |
|---|---|
| 20 | H4 trend in trade direction (close > EMA50 > EMA200, EMA50 sloping) |
| 20 | H1 trend in trade direction |
| 15 | M15 EMA20/EMA50 aligned, price on the right side of EMA20 |
| 15 | MACD histogram in direction and growing (10 for a fresh cross) |
| 10 | RSI 50–68 for buys / 32–50 for sells |
| 10 | Pullback to EMA20 then bounce |
| 10 | ADX ≥ 20 (trending market) |
| −10 | Price stretched outside the Bollinger Band |

A signal is sent when the score is **≥ 65** and: the H1 trend is not against it, the signal
candle closes in the trade direction, RSI isn't extreme, it's London/New York hours
(07:00–20:00 UTC, i.e. 10:00–23:00 Tanzania), the spread is normal, there's no open signal
on that pair, and the 2-hour cooldown has passed.

**Stop Loss** sits beyond the last 10 candles' swing, between 1.5× and 3× ATR.
**TP1/TP2/TP3** are 1R, 2R, 3R. After TP1, the bot tells followers to move SL to entry.

## Setup on your PC (Windows, PowerShell, MT5 mode)

1. **Install MetaTrader 5** and log in to your broker (use a **demo** account first).
   Open charts for the 4 pairs once so MT5 downloads their history.
   In MT5: *Tools → Options → Charts → Max bars in chart* → set to *Unlimited* (for backtests).

2. **Install Python 3.10+** from python.org (tick "Add to PATH"), then in the project folder:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Create the Telegram bot**
   - Chat with **@BotFather** → `/newbot` → copy the token.
   - Create a channel, add your bot as **Administrator** (with "Post messages").
   - Chat id: `@channelname` for a public channel. For a private channel, post something,
     forward it to **@userinfobot** (or open `https://api.telegram.org/bot<TOKEN>/getUpdates`)
     to get the `-100…` id.

4. **Configure**
   ```powershell
   copy .env.example .env
   notepad .env
   ```
   If your broker shows pairs as `EURUSDm` (or similar) in Market Watch, set `SYMBOL_SUFFIX=m`.

5. **Backtest first**
   ```powershell
   python run_backtest.py
   ```
   Shows win rate, total R, profit factor and max drawdown per pair, and saves every trade to
   `backtest_trades.csv`. Tune `bot/config.py` and re-run until you're happy.

6. **Run it**
   ```powershell
   python run_bot.py
   ```
   Without a Telegram token it runs in dry-run mode and prints signals to the console.
   Signals and results are stored in `signals.db`; logs in `bot.log`.

## Keeping it running 24/5 (cloud hosting)

Set `DATA_SOURCE=twelvedata` and the bot no longer needs MetaTrader, so it runs on any
Linux server. Prices come from Twelve Data's free plan (800 requests/day, 8/minute).
The bot caches candles and only downloads after a new candle closes, and it skips weekends,
so 4 pairs use about 400–500 requests a day. Each extra pair adds ~100–120.

Differences vs MT5 mode: prices are from Twelve Data rather than your broker, so levels can
differ by a few pips (more on gold); a typical spread is added to entries
(`ASSUMED_SPREAD_PIPS`); and open signals are checked on every M15 close instead of every minute.

### Deploy free on Render + Supabase (recommended to start)

**1. Supabase table.** In your Supabase project: *SQL Editor → New query*, paste
`supabase_schema.sql`, *Run*. It creates `bot_signals` with Row Level Security on.
Then *Project Settings → API Keys* and copy the project URL and the **secret** key
(`sb_secret_...`, or the older `service_role` key). Server-side only — never put it in
frontend code or commit it to GitHub.

**2. Twelve Data key.** Sign up free at twelvedata.com and copy the API key.

**3. Render.** Push this folder to GitHub, then in Render: *New → Blueprint* → pick the
repo. `render.yaml` creates a **free web service** and asks for:
```
TWELVEDATA_API_KEY   TELEGRAM_BOT_TOKEN   TELEGRAM_CHAT_ID
SUPABASE_URL         SUPABASE_SERVICE_KEY
```
(`DATA_SOURCE=twelvedata` and `STORAGE=supabase` are already set.) Deploy, then open
`https://<your-service>.onrender.com/health` — you should see `{"status": "ok", ...}`.

**4. Keep it awake.** Free Render services sleep after 15 minutes without traffic. Create a
free monitor at **uptimerobot.com**: *New monitor → HTTP(s)* → URL
`https://<your-service>.onrender.com/health` → interval **5 minutes**. It also emails you if
the bot stops (`/health` returns 503 when the loop is stuck).

**Free-hours warning:** Render gives **750 free instance hours per month per workspace**,
shared by all your free services. This bot uses ~744 hours when kept awake all month, so
any other free service in the same workspace that is awake (e.g. another project's API)
will push you over, and Render then suspends **all** free services until the next month.
Put the bot in its own Render workspace/account, or move it to a paid worker.

### Upgrading later (no code changes)

- **Render paid Background Worker (~$7/mo):** always on, no pinger needed. The `Procfile`
  already defines the `worker`; keep `STORAGE=supabase`.
- **Railway Hobby (~$5/mo):** `railway.json` sets the start command. Add the same variables;
  either keep `STORAGE=supabase` or attach a volume at `/data` with `DB_PATH=/data/signals.db`.
- **Windows VPS with MT5:** `DATA_SOURCE=mt5` for your broker's exact prices.

### Test cloud mode on your laptop first

In `.env` set `DATA_SOURCE=twelvedata`, `STORAGE=supabase` and the keys, plus `PORT=8000`,
then `python run_bot.py` and open http://localhost:8000/health. No MT5 needed.
`python run_backtest.py` works in this mode too, but only on the last 5000 M15 candles
(~7 weeks); MT5 gives much longer history.

### Reading the signals from Supabase

Every signal and its outcome is a row in `bot_signals` (entry, SL, TPs, score, reasons,
status, `tp_hit`, `result_r`). To show them on a website, add a read policy for
signed-in users (a commented example is at the bottom of `supabase_schema.sql`) and
query the table with the publishable key, e.g. latest 20 by `created_at`.

## Tuning (bot/config.py)

| Setting | Effect |
|---|---|
| `MIN_SCORE` | Higher = fewer, stronger signals (try 70–80) |
| `SYMBOLS` | Add/remove pairs (also add their `MAX_SPREAD_PIPS`) |
| `SL_ATR_MULT`, `TP_R` | Stop width and target distances |
| `SESSION_START_UTC/END_UTC` | Trading hours |
| `COOLDOWN_BARS`, `MAX_SIGNALS_PER_DAY` | Signal frequency |

## Honest notes

- No indicator strategy wins all the time. Judge it on **backtest + a few weeks of demo
  results**, not single trades. Tell followers to risk only 1–2% per trade.
- The backtest assumes a fixed spread and no slippage, and checks SL before TP when both
  fall inside one candle (conservative).
- High-impact news (NFP, CPI, FOMC) can blow through stops. A news filter is a good next step.
- This is an educational tool, not financial advice.
