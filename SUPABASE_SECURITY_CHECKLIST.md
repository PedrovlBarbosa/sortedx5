# Checklist de Seguranca - SortedX5 + Supabase

## 1) Chaves e Segredos
- Nao usar service_role no app publicado para usuarios finais.
- Usar anon key no app do Streamlit Cloud.
- Guardar credenciais apenas em Secrets do Streamlit Cloud.
- Confirmar que .streamlit/secrets.toml nao vai para o Git.

## 2) RLS e Politicas
- Executar o SQL de [supabase_rls.sql](supabase_rls.sql).
- Confirmar que RLS esta enabled nas tabelas players, matches e match_players.
- Revisar politicas e remover permissoes desnecessarias.
- Bloquear delete para anon/authenticated se nao for necessario.

## 3) Modelo de Acesso
- Sem login de usuario: manter escopo minimo de escrita (somente insert/update necessario).
- Com login: trocar politicas para regras por usuario.
- Para maior seguranca: criar funcoes RPC no Supabase para registrar partida com validacoes no servidor.

## 4) Auditoria e Observabilidade
- Revisar Logs no Supabase periodicamente.
- Configurar alertas de uso e limites de recurso.
- Monitorar taxas de erro de insert/update.

## 5) Deploy no Streamlit Cloud
- Em Secrets do app, definir [app] data_mode = "supabase".
- Em Secrets do app, definir [supabase] url e key (anon key).
- Fazer deploy e validar que o sidebar mostra modo SUPABASE.
- Rodar teste funcional: criar jogador, sortear times, registrar partida e confirmar no painel do Supabase.

## 6) Rotina de Backup e Recuperacao
- Exportar dados periodicamente (pg_dump ou backup interno Supabase, conforme plano).
- Testar restauracao em ambiente de homologacao.
- Documentar responsavel e periodicidade do backup.
