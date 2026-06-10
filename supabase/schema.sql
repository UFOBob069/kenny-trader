-- VWAP Event Trading Copilot — Supabase schema

create table if not exists signals (
    id text primary key,
    created_at timestamptz not null,
    symbol text not null,
    direction text not null,
    setup text not null,
    entry numeric not null,
    stop numeric not null,
    target numeric not null,
    confidence numeric not null default 0,
    status text not null,
    breakdown jsonb
);

create table if not exists trades (
    id text primary key,
    signal_id text references signals(id),
    symbol text not null,
    direction text not null,
    quantity integer not null,
    entry numeric not null,
    stop numeric not null,
    target numeric not null,
    confidence numeric not null default 0,
    status text not null,
    opened_at timestamptz not null,
    closed_at timestamptz,
    exit_price numeric,
    realized_pnl numeric
);

create table if not exists watchlist (
    symbol text primary key,
    added_at timestamptz not null default now(),
    note text
);

create table if not exists settings (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);

create index if not exists idx_signals_created on signals (created_at desc);
create index if not exists idx_trades_status on trades (status);
create index if not exists idx_trades_closed on trades (closed_at desc);
