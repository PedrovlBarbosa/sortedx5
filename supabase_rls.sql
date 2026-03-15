-- ============================================================
-- SortedX5 - RLS + Politicas para uso com anon key no cliente
-- ============================================================
-- Importante: execute apos criar o schema base (supabase_schema.sql)

-- 1) Habilitar RLS
alter table players enable row level security;
alter table matches enable row level security;
alter table match_players enable row level security;

-- 2) Leitura publica autenticada ou anonima (ajuste conforme sua necessidade)
create policy players_read_all
on players for select
to anon, authenticated
using (true);

create policy matches_read_all
on matches for select
to anon, authenticated
using (true);

create policy match_players_read_all
on match_players for select
to anon, authenticated
using (true);

-- 3) Escrita: opcao simples para app publico sem login
-- Se o app nao tiver autenticacao de usuario, a opcao mais simples
-- e permitir inserts/updates para anon. Em producao, considere migrar
-- para RPC com validações de servidor.

create policy players_insert_anon
on players for insert
to anon, authenticated
with check (true);

create policy players_update_anon
on players for update
to anon, authenticated
using (true)
with check (true);

create policy matches_insert_anon
on matches for insert
to anon, authenticated
with check (winner in ('A', 'B'));

create policy match_players_insert_anon
on match_players for insert
to anon, authenticated
with check (team in ('A', 'B'));

-- Opcional: bloquear delete para reduzir risco de perda acidental
revoke delete on table players from anon, authenticated;
revoke delete on table matches from anon, authenticated;
revoke delete on table match_players from anon, authenticated;
