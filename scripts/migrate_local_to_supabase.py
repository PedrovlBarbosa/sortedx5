"""
Migra dados do banco local SQLite do SortedX5 para o Supabase.

Uso:
python scripts/migrate_local_to_supabase.py \
    --sqlite-path sortedx5_local.db

Opcionalmente, voce pode sobrescrever credenciais por linha de comando:
python scripts/migrate_local_to_supabase.py \
    --supabase-url https://SEU-PROJETO.supabase.co \
    --supabase-key SUA_SERVICE_ROLE_KEY

Observacoes:
- Mantem relacionamento entre players, matches e match_players.
- Se o jogador ja existir no Supabase pelo nome, reaproveita esse jogador.
- Opcionalmente atualiza rating dos jogadores existentes com --update-existing-ratings.
"""

from __future__ import annotations

import argparse
import configparser
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supabase import Client, create_client


@dataclass
class MigrationStats:
    local_players: int = 0
    local_matches: int = 0
    local_match_players: int = 0
    inserted_players: int = 0
    reused_players: int = 0
    updated_players: int = 0
    inserted_matches: int = 0
    inserted_match_players: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migra dados SQLite para Supabase")
    parser.add_argument("--sqlite-path", default="sortedx5_local.db", help="Caminho do arquivo SQLite")
    parser.add_argument(
        "--secrets-path",
        default=".streamlit/secrets.toml",
        help="Caminho do secrets.toml usado para ler [supabase].url e [supabase].key",
    )
    parser.add_argument("--supabase-url", help="URL do projeto Supabase (sobrescreve o secrets)")
    parser.add_argument("--supabase-key", help="Chave do Supabase (sobrescreve o secrets)")
    parser.add_argument(
        "--update-existing-ratings",
        action="store_true",
        help="Atualiza o rating no Supabase quando o jogador ja existe pelo nome",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Somente simula e mostra o que seria migrado, sem gravar no Supabase",
    )
    return parser.parse_args()


def _load_supabase_from_secrets(secrets_path: str) -> tuple[str | None, str | None]:
    path = Path(secrets_path)
    if not path.exists():
        return None, None

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    if not parser.has_section("supabase"):
        return None, None

    url = parser.get("supabase", "url", fallback=None)
    key = parser.get("supabase", "key", fallback=None)

    if url:
        url = url.strip().strip('"').strip("'")
    if key:
        key = key.strip().strip('"').strip("'")

    return url, key


def resolve_supabase_credentials(args: argparse.Namespace) -> tuple[str, str]:
    secret_url, secret_key = _load_supabase_from_secrets(args.secrets_path)

    supabase_url = args.supabase_url or secret_url
    supabase_key = args.supabase_key or secret_key

    if not supabase_url or not supabase_key:
        raise ValueError(
            "Credenciais do Supabase ausentes. Preencha [supabase].url e [supabase].key "
            f"em {args.secrets_path} ou passe --supabase-url e --supabase-key."
        )

    return supabase_url, supabase_key


def connect_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_sqlite_data(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    players = [dict(r) for r in conn.execute("select * from players order by created_at asc").fetchall()]
    matches = [dict(r) for r in conn.execute("select * from matches order by created_at asc").fetchall()]
    match_players = [dict(r) for r in conn.execute("select * from match_players order by id asc").fetchall()]
    return players, matches, match_players


def get_or_create_player(
    sb: Client,
    player: dict[str, Any],
    update_existing_ratings: bool,
    dry_run: bool,
    stats: MigrationStats,
) -> str:
    name = player["name"]
    rating = int(player["rating"])

    existing = sb.table("players").select("id, rating").eq("name", name).limit(1).execute().data
    if existing:
        stats.reused_players += 1
        existing_id = existing[0]["id"]
        existing_rating = int(existing[0]["rating"])
        if update_existing_ratings and existing_rating != rating and not dry_run:
            sb.table("players").update({"rating": rating}).eq("id", existing_id).execute()
            stats.updated_players += 1
        return existing_id

    stats.inserted_players += 1
    if dry_run:
        return f"DRY_PLAYER_{name}"

    row = (
        sb.table("players")
        .insert(
            {
                "name": name,
                "rating": rating,
                "created_at": player.get("created_at"),
            }
        )
        .execute()
        .data[0]
    )
    return row["id"]


def migrate(
    sqlite_path: str,
    supabase_url: str,
    supabase_key: str,
    update_existing_ratings: bool,
    dry_run: bool,
) -> MigrationStats:
    stats = MigrationStats()

    conn = connect_sqlite(sqlite_path)
    players, matches, match_players = load_sqlite_data(conn)
    conn.close()

    stats.local_players = len(players)
    stats.local_matches = len(matches)
    stats.local_match_players = len(match_players)

    sb = create_client(supabase_url, supabase_key)

    player_id_map: dict[str, str] = {}
    for p in players:
        new_id = get_or_create_player(sb, p, update_existing_ratings, dry_run, stats)
        player_id_map[p["id"]] = new_id

    match_id_map: dict[str, str] = {}
    for m in matches:
        stats.inserted_matches += 1
        if dry_run:
            match_id_map[m["id"]] = f"DRY_MATCH_{m['id']}"
            continue

        row = (
            sb.table("matches")
            .insert(
                {
                    "winner": m["winner"],
                    "team_a_avg": m["team_a_avg"],
                    "team_b_avg": m["team_b_avg"],
                    "created_at": m.get("created_at"),
                }
            )
            .execute()
            .data[0]
        )
        match_id_map[m["id"]] = row["id"]

    payload: list[dict[str, Any]] = []
    for mp in match_players:
        mapped_player = player_id_map.get(mp["player_id"])
        mapped_match = match_id_map.get(mp["match_id"])
        if not mapped_player or not mapped_match:
            continue

        payload.append(
            {
                "match_id": mapped_match,
                "player_id": mapped_player,
                "team": mp["team"],
                "rating_before": int(mp["rating_before"]),
                "rating_after": int(mp["rating_after"]),
            }
        )

    stats.inserted_match_players = len(payload)

    if payload and not dry_run:
        sb.table("match_players").insert(payload).execute()

    return stats


def print_stats(stats: MigrationStats, dry_run: bool) -> None:
    mode = "SIMULACAO (dry-run)" if dry_run else "EXECUCAO"
    print(f"\n=== MIGRACAO {mode} ===")
    print(f"Players no SQLite:        {stats.local_players}")
    print(f"Matches no SQLite:        {stats.local_matches}")
    print(f"MatchPlayers no SQLite:   {stats.local_match_players}")
    print(f"Players inseridos:        {stats.inserted_players}")
    print(f"Players reaproveitados:   {stats.reused_players}")
    print(f"Players atualizados:      {stats.updated_players}")
    print(f"Matches inseridos:        {stats.inserted_matches}")
    print(f"MatchPlayers inseridos:   {stats.inserted_match_players}")


def main() -> int:
    args = parse_args()

    try:
        supabase_url, supabase_key = resolve_supabase_credentials(args)

        stats = migrate(
            sqlite_path=args.sqlite_path,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            update_existing_ratings=args.update_existing_ratings,
            dry_run=args.dry_run,
        )
        print_stats(stats, dry_run=args.dry_run)
        return 0
    except FileNotFoundError:
        print(f"Arquivo SQLite nao encontrado: {args.sqlite_path}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"Erro no SQLite: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Erro na migracao: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
