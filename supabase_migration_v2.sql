-- ============================================================
-- SortedX5 - Migracao V2 (CS + LoL + Lanes)
-- ============================================================
-- Execute este script no SQL Editor do Supabase.
-- Seguro para rodar mais de uma vez (idempotente na maior parte dos objetos).

begin;

-- 1) players: ratings separados + lanes de preferencia
alter table if exists players
  add column if not exists cs_rating integer,
  add column if not exists lol_rating integer,
  add column if not exists lol_lane_1 text,
  add column if not exists lol_lane_2 text,
  add column if not exists lol_lane_3 text;

-- Backfill para bancos antigos que tinham apenas rating unico
update players
set cs_rating = coalesce(cs_rating, rating, 1000)
where cs_rating is null;

update players
set lol_rating = coalesce(lol_rating, rating, 1000)
where lol_rating is null;

-- Garantir not null nos novos ratings
alter table players
  alter column cs_rating set not null,
  alter column lol_rating set not null;

-- 2) matches: indicar o jogo da partida
alter table if exists matches
  add column if not exists game text;

update matches
set game = coalesce(game, 'CS')
where game is null;

alter table matches
  alter column game set not null,
  alter column game set default 'CS';

-- CHECK de game
alter table matches drop constraint if exists matches_game_check;
alter table matches
  add constraint matches_game_check check (game in ('CS', 'LoL'));

-- 3) match_players: role/lane usada na partida (principalmente LoL)
alter table if exists match_players
  add column if not exists role text;

-- 4) indices novos
create index if not exists idx_players_cs_rating on players(cs_rating desc);
create index if not exists idx_players_lol_rating on players(lol_rating desc);
create index if not exists idx_matches_game on matches(game);
create index if not exists idx_match_players_role on match_players(role);

-- 5) repositorio de prints dos jogos
create table if not exists game_prints (
  id bigserial primary key,
  title text not null,
  game text not null default 'Geral',
  note text,
  image_b64 text not null,
  mime_type text not null,
  created_by text,
  created_at timestamptz not null default now()
);

create index if not exists idx_game_prints_created on game_prints(created_at desc);

-- 6) usuarios do app (login interno + perfis)
create table if not exists auth_users (
  id text primary key default ('user_' || replace(gen_random_uuid()::text, '-', '')),
  username text not null unique,
  password_sha256 text not null,
  role text not null,
  recovery_sha256 text not null,
  failed_attempts integer not null default 0,
  locked_until timestamptz,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists idx_auth_users_username on auth_users(username);

alter table auth_users drop constraint if exists auth_users_role_check;
alter table auth_users
  add constraint auth_users_role_check check (role in ('admin_super', 'admin', 'standard', 'viewer'));

commit;

-- Verificacao rapida (opcional):
-- select column_name, data_type
-- from information_schema.columns
-- where table_name in ('players', 'matches', 'match_players')
-- order by table_name, ordinal_position;
