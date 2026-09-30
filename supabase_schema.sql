-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Creates the table the signal bot writes to.

create table if not exists public.bot_signals (
  id            bigint generated always as identity primary key,
  symbol        text not null,                 -- EURUSD, XAUUSD ...
  broker_symbol text,                          -- name used by the price feed (EUR/USD, EURUSDm ...)
  side          text not null check (side in ('BUY', 'SELL')),
  entry         double precision not null,
  sl            double precision not null,     -- current stop (moves to entry after TP1)
  sl_initial    double precision not null,
  tps           jsonb not null,                -- [tp1, tp2, tp3]
  score         integer,
  reasons       text,
  digits        integer,
  created_at    timestamptz not null default now(),
  last_checked  timestamptz,
  closed_at     timestamptz,
  status        text not null default 'OPEN'
                check (status in ('OPEN', 'TP', 'SL', 'BE', 'EXPIRED')),
  tp_hit        integer not null default 0,    -- how many targets were reached (0-3)
  result_r      double precision,              -- final result in R (risk multiples)
  message_id    bigint                         -- Telegram message, for threaded updates
);

create index if not exists bot_signals_status_idx on public.bot_signals (status);
create index if not exists bot_signals_symbol_created_idx on public.bot_signals (symbol, created_at desc);
create index if not exists bot_signals_closed_idx on public.bot_signals (closed_at);

-- Lock the table down. The bot uses the service_role/secret key, which bypasses RLS,
-- so it can still read and write. Nobody else can until you add a policy.
alter table public.bot_signals enable row level security;

-- LATER, if a website/dashboard should show the signals: let signed-in users read them.
-- (Tighten this to paying members using your own profiles/membership table.)
-- create policy "signed-in users can read signals"
--   on public.bot_signals for select
--   to authenticated
--   using (true);
