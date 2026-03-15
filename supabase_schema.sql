-- ============================================================
-- SortedX5 - Schema do Banco de Dados (Supabase / PostgreSQL)
-- ============================================================
-- Execute este SQL no SQL Editor do Supabase para criar as tabelas.

-- 1. Tabela de jogadores
create table players (
  id         uuid primary key default gen_random_uuid(),
  name       text not null unique,
  rating     integer not null default 1000,
  created_at timestamptz not null default now()
);

-- 2. Tabela de partidas
create table matches (
  id          uuid primary key default gen_random_uuid(),
  winner      text not null check (winner in ('A', 'B')),
  team_a_avg  real not null,
  team_b_avg  real not null,
  created_at  timestamptz not null default now()
);

-- 3. Tabela associativa: jogadores de cada partida
create table match_players (
  id            uuid primary key default gen_random_uuid(),
  match_id      uuid not null references matches(id) on delete cascade,
  player_id     uuid not null references players(id) on delete cascade,
  team          text not null check (team in ('A', 'B')),
  rating_before integer not null,
  rating_after  integer not null
);

-- Índices para consultas frequentes
create index idx_match_players_match on match_players(match_id);
create index idx_match_players_player on match_players(player_id);
create index idx_matches_created on matches(created_at desc);
create index idx_players_rating on players(rating desc);

-- Habilitar Row Level Security (opcional, desabilite se usar service_role key)
-- alter table players enable row level security;
-- alter table matches enable row level security;
-- alter table match_players enable row level security;
