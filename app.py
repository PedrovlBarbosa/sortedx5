"""
SortedX5 - Matchmaking 5v5 (CS + LoL)
Streamlit + Local SQLite (default) / Supabase (optional)
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from itertools import combinations, permutations
import random
import sqlite3
from typing import Any, cast
from uuid import uuid4

import streamlit as st
try:
    import extra_streamlit_components as stx  # type: ignore[import-not-found]
except ImportError:
    stx = None

try:
    from supabase import Client, create_client
except ImportError:
    Client = object  # type: ignore[assignment]
    create_client = None

st.set_page_config(page_title="SortedX5", page_icon="🎯", layout="wide")

LOCAL_DB_PATH = "sortedx5_local.db"
DEFAULT_RATING = 1000
RATING_DELTA = 25
TEAM_SIZE = 5
LANES = ["Top", "Jungle", "Mid", "ADC", "Support"]
GAME_OPTIONS = ["CS", "LoL"]
ALLOWED_ROLES = {"admin", "standard"}


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

        :root {
            --sx-bg: #0A0F16;
            --sx-bg-2: #0E141D;
            --sx-text: #FFFFFF;
            --sx-muted: #94A3B8;
            --sx-card: #171E28;
            --sx-border: #263244;
            --sx-primary: #45E586;
            --sx-royal: #2D4EA2;
        }

        .stApp {
            background:
                radial-gradient(1100px 440px at 4% -10%, rgba(69, 229, 134, 0.15), transparent),
                radial-gradient(1100px 440px at 95% -10%, rgba(45, 78, 162, 0.15), transparent),
                linear-gradient(180deg, var(--sx-bg) 0%, var(--sx-bg-2) 100%);
            color: var(--sx-text);
        }

        h1, h2, h3, h4, p, span, div, label, .stMarkdown {
            font-family: 'Space Grotesk', sans-serif;
            color: var(--sx-text);
        }

        [data-testid="stSidebar"] {
            background: var(--sx-card);
            border-right: 1px solid var(--sx-border);
        }

        [data-testid="stSidebar"] * {
            color: var(--sx-text);
        }

        [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
            color: var(--sx-text);
        }

        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stNumberInputContainer"] input,
        div[data-testid="stTextArea"] textarea,
        .stMultiSelect [data-baseweb="tag"] {
            background: #0F1722;
            color: var(--sx-text);
            border-color: var(--sx-border);
        }

        /* Botao principal */
        .stButton > button,
        .stDownloadButton > button {
            background: linear-gradient(180deg, #4bf19a 0%, #38cf79 100%);
            color: #0A0F16;
            border: 1px solid #2dbd6b;
            border-radius: 10px;
            font-weight: 600;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: var(--sx-primary);
            box-shadow: 0 4px 14px rgba(69, 229, 134, 0.25);
        }

        /* Botao secundario custom */
        .sx-secondary-btn {
            display: inline-block;
            background: var(--sx-royal);
            color: #FFFFFF;
            border-radius: 10px;
            border: 1px solid #4163be;
            padding: 8px 14px;
            font-weight: 600;
            text-decoration: none;
        }

        .sx-secondary-btn:hover {
            filter: brightness(1.08);
            box-shadow: 0 6px 18px rgba(45, 78, 162, 0.35);
        }

        /* Card custom para metricas */
        .sx-metric-card {
            background: var(--sx-card);
            border: 1px solid var(--sx-border);
            border-radius: 16px;
            padding: 14px 16px;
            box-shadow: 0 8px 24px rgba(2, 6, 23, 0.35);
            margin-bottom: 10px;
            transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        }

        .sx-metric-card:hover {
            transform: translateY(-2px);
            border-color: #3d526d;
            box-shadow: 0 12px 30px rgba(2, 6, 23, 0.45);
        }

        .sx-kpi {
            display: inline-block;
            padding: 8px 12px;
            border-radius: 999px;
            border: 1px solid #2f3f56;
            background: #101A27;
            margin-right: 8px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 12px;
            color: #E2E8F0;
        }

        .sx-sub {
            color: var(--sx-muted);
            font-size: 13px;
            margin-top: -6px;
            margin-bottom: 8px;
        }

        small, .stCaption, [data-testid="stCaptionContainer"] {
            color: #94A3B8 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_role(role: Any) -> str:
    value = str(role or "standard").strip().lower()
    return value if value in ALLOWED_ROLES else "standard"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verify_secret(password: str, user_cfg: dict[str, Any]) -> bool:
    hash_value = str(user_cfg.get("password_sha256") or "").strip().lower()
    plain_value = str(user_cfg.get("password") or "")

    if hash_value:
        return hmac.compare_digest(_sha256_text(password), hash_value)
    if plain_value:
        return hmac.compare_digest(password, plain_value)
    return False


def _get_auth_users() -> dict[str, dict[str, Any]]:
    auth_cfg = st.secrets.get("auth", {})
    raw_users = auth_cfg.get("users", []) if isinstance(auth_cfg, Mapping) else []
    users: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_users, list):
        return users

    for raw in raw_users:
        if not isinstance(raw, dict):
            continue
        username = str(raw.get("username") or "").strip().lower()
        if not username:
            continue
        users[username] = {
            "username": username,
            "role": _normalize_role(raw.get("role")),
            "password": str(raw.get("password") or ""),
            "password_sha256": str(raw.get("password_sha256") or ""),
        }
    return users


def _auth_enabled() -> bool:
    auth_cfg = st.secrets.get("auth", {})
    if isinstance(auth_cfg, Mapping) and "enabled" in auth_cfg:
        return bool(auth_cfg.get("enabled"))
    return True


def get_cookie_manager() -> Any:
    if stx is None:
        return None
    if "_sx_cookie_manager" not in st.session_state:
        st.session_state["_sx_cookie_manager"] = stx.CookieManager()
    return st.session_state["_sx_cookie_manager"]


def _auth_cookie_name() -> str:
    auth_cfg = st.secrets.get("auth", {})
    if isinstance(auth_cfg, Mapping) and auth_cfg.get("cookie_name"):
        return str(auth_cfg.get("cookie_name"))
    return "sortedx5_auth"


def _auth_cookie_secret() -> str:
    auth_cfg = st.secrets.get("auth", {})
    if isinstance(auth_cfg, Mapping) and auth_cfg.get("cookie_secret"):
        return str(auth_cfg.get("cookie_secret"))
    return "sortedx5-dev-secret-change-me"


def _auth_cookie_days() -> int:
    auth_cfg = st.secrets.get("auth", {})
    if isinstance(auth_cfg, Mapping) and auth_cfg.get("cookie_days") is not None:
        raw_days = auth_cfg.get("cookie_days")
        if raw_days is None:
            return 7
        try:
            return max(1, int(str(raw_days)))
        except Exception:
            return 7
    return 7


def _auth_sign(payload: str) -> str:
    secret = _auth_cookie_secret().encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _create_auth_token(username: str, role: str) -> str:
    exp_ts = int((datetime.now(timezone.utc) + timedelta(days=_auth_cookie_days())).timestamp())
    payload = f"{username}|{role}|{exp_ts}"
    signature = _auth_sign(payload)
    token_raw = f"{payload}|{signature}"
    return base64.urlsafe_b64encode(token_raw.encode("utf-8")).decode("ascii")


def _decode_auth_token(token: str) -> tuple[str, str] | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, role, exp_ts, signature = decoded.split("|", 3)
        payload = f"{username}|{role}|{exp_ts}"
        if not hmac.compare_digest(signature, _auth_sign(payload)):
            return None
        if int(exp_ts) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return username, _normalize_role(role)
    except Exception:
        return None


def _set_auth_cookie(username: str, role: str) -> None:
    cookie = get_cookie_manager()
    if cookie is None:
        return
    token = _create_auth_token(username, role)
    cookie.set(
        _auth_cookie_name(),
        token,
        expires_at=datetime.utcnow() + timedelta(days=_auth_cookie_days()),
        key="set_auth_cookie",
    )


def _clear_auth_cookie() -> None:
    cookie = get_cookie_manager()
    if cookie is None:
        return
    try:
        cookie.delete(_auth_cookie_name(), key="del_auth_cookie")
    except Exception:
        cookie.set(
            _auth_cookie_name(),
            "",
            expires_at=datetime.utcnow() - timedelta(days=1),
            key="expire_auth_cookie",
        )


def ensure_login() -> tuple[str, str]:
    if not _auth_enabled():
        return "local", "admin"

    users = _get_auth_users()
    if not users:
        st.error("Autenticacao habilitada, mas sem usuarios em st.secrets['auth']['users'].")
        st.code(
            """
[auth]
enabled = true

[[auth.users]]
username = "admin"
password_sha256 = "<sha256_da_senha>"
role = "admin"

[[auth.users]]
username = "guest"
password_sha256 = "<sha256_da_senha>"
role = "standard"
            """.strip()
        )
        st.info("Para gerar hash SHA-256 localmente: python -c \"import hashlib; print(hashlib.sha256('SENHA'.encode()).hexdigest())\"")
        st.stop()

    if st.session_state.get("auth_ok"):
        return str(st.session_state.get("auth_user")), _normalize_role(st.session_state.get("auth_role"))

    cookie = get_cookie_manager()
    if cookie is not None:
        cookie_token = cookie.get(_auth_cookie_name())
        if cookie_token:
            parsed = _decode_auth_token(str(cookie_token))
            if parsed:
                user_from_cookie, role_from_cookie = parsed
                user_cfg = users.get(user_from_cookie)
                if user_cfg and _normalize_role(user_cfg.get("role")) == role_from_cookie:
                    st.session_state["auth_ok"] = True
                    st.session_state["auth_user"] = user_from_cookie
                    st.session_state["auth_role"] = role_from_cookie
                    return user_from_cookie, role_from_cookie

    st.markdown("## Login")
    st.caption("Acesso restrito por perfil.")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Senha", type="password")
        remember = st.checkbox("Manter login neste dispositivo", value=True)
        submit = st.form_submit_button("Entrar")

    if submit:
        uname = username.strip().lower()
        user = users.get(uname)
        if not user or not _verify_secret(password, user):
            st.error("Usuario ou senha invalidos.")
        else:
            st.session_state["auth_ok"] = True
            st.session_state["auth_user"] = user["username"]
            st.session_state["auth_role"] = user["role"]
            if remember:
                _set_auth_cookie(user["username"], user["role"])
            st.rerun()

    st.stop()


def normalize_player(player: dict[str, Any]) -> dict[str, Any]:
    base = int(player.get("rating") or DEFAULT_RATING)
    player["cs_rating"] = int(player.get("cs_rating") or base)
    player["lol_rating"] = int(player.get("lol_rating") or base)
    player["lol_lane_1"] = player.get("lol_lane_1") or ""
    player["lol_lane_2"] = player.get("lol_lane_2") or ""
    player["lol_lane_3"] = player.get("lol_lane_3") or ""
    return player


class DataStore:
    def is_local(self) -> bool:
        raise NotImplementedError

    def load_players(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def find_player_by_name(self, name: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def add_player(
        self,
        name: str,
        cs_rating: int,
        lol_rating: int,
        lane_1: str,
        lane_2: str,
        lane_3: str,
    ) -> None:
        raise NotImplementedError

    def update_player_profile(
        self,
        player_id: str,
        name: str,
        cs_rating: int,
        lol_rating: int,
        lane_1: str,
        lane_2: str,
        lane_3: str,
    ) -> None:
        raise NotImplementedError

    def delete_player(self, player_id: str) -> None:
        raise NotImplementedError

    def create_match(self, game: str, winner: str, team_a_avg: float, team_b_avg: float) -> str:
        raise NotImplementedError

    def update_player_rating(self, player_id: str, game: str, new_rating: int) -> None:
        raise NotImplementedError

    def add_match_players(self, rows: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def get_match_players(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_matches(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_recent_matches(self, game: str, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_match_players_by_match(self, match_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def add_game_print(self, title: str, game: str, note: str, image_b64: str, mime_type: str, created_by: str) -> None:
        raise NotImplementedError

    def get_recent_game_prints(self, limit: int = 60) -> list[dict[str, Any]]:
        raise NotImplementedError

    def delete_game_print(self, print_id: Any) -> None:
        raise NotImplementedError


class LocalSQLiteStore(DataStore):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def is_local(self) -> bool:
        return True

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _column_exists(self, conn: sqlite3.Connection, table: str, col: str) -> bool:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(c[1] == col for c in cols)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                create table if not exists players (
                    id text primary key,
                    name text not null unique,
                    rating integer not null default 1000,
                    cs_rating integer,
                    lol_rating integer,
                    lol_lane_1 text,
                    lol_lane_2 text,
                    lol_lane_3 text,
                    created_at text not null
                );

                create table if not exists matches (
                    id text primary key,
                    game text not null default 'CS',
                    winner text not null check (winner in ('A', 'B')),
                    team_a_avg real not null,
                    team_b_avg real not null,
                    created_at text not null
                );

                create table if not exists match_players (
                    id integer primary key autoincrement,
                    match_id text not null,
                    player_id text not null,
                    team text not null check (team in ('A', 'B')),
                    role text,
                    rating_before integer not null,
                    rating_after integer not null,
                    foreign key (match_id) references matches(id) on delete cascade,
                    foreign key (player_id) references players(id) on delete cascade
                );

                create table if not exists game_prints (
                    id integer primary key autoincrement,
                    title text not null,
                    game text not null,
                    note text,
                    image_b64 text not null,
                    mime_type text not null,
                    created_by text,
                    created_at text not null
                );
                """
            )

            if not self._column_exists(conn, "players", "cs_rating"):
                conn.execute("alter table players add column cs_rating integer")
            if not self._column_exists(conn, "players", "lol_rating"):
                conn.execute("alter table players add column lol_rating integer")
            if not self._column_exists(conn, "players", "lol_lane_1"):
                conn.execute("alter table players add column lol_lane_1 text")
            if not self._column_exists(conn, "players", "lol_lane_2"):
                conn.execute("alter table players add column lol_lane_2 text")
            if not self._column_exists(conn, "players", "lol_lane_3"):
                conn.execute("alter table players add column lol_lane_3 text")
            if not self._column_exists(conn, "matches", "game"):
                conn.execute("alter table matches add column game text default 'CS'")
            if not self._column_exists(conn, "match_players", "role"):
                conn.execute("alter table match_players add column role text")

            conn.execute("update players set cs_rating = coalesce(cs_rating, rating, ?)", (DEFAULT_RATING,))
            conn.execute("update players set lol_rating = coalesce(lol_rating, rating, ?)", (DEFAULT_RATING,))

            # Criar indices apos garantir que colunas legadas ja foram migradas.
            conn.executescript(
                """
                create index if not exists idx_players_cs on players(cs_rating desc);
                create index if not exists idx_players_lol on players(lol_rating desc);
                create index if not exists idx_matches_created on matches(created_at desc);
                create index if not exists idx_matches_game on matches(game);
                create index if not exists idx_mp_match on match_players(match_id);
                create index if not exists idx_prints_created on game_prints(created_at desc);
                """
            )

    def load_players(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                select id, name, rating, cs_rating, lol_rating, lol_lane_1, lol_lane_2, lol_lane_3, created_at
                from players
                order by cs_rating desc, lol_rating desc, name asc
                """
            ).fetchall()
        return [normalize_player(dict(r)) for r in rows]

    def find_player_by_name(self, name: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                select id, name, rating, cs_rating, lol_rating, lol_lane_1, lol_lane_2, lol_lane_3, created_at
                from players where name = ?
                """,
                (name,),
            ).fetchone()
        return normalize_player(dict(row)) if row else None

    def add_player(
        self,
        name: str,
        cs_rating: int,
        lol_rating: int,
        lane_1: str,
        lane_2: str,
        lane_3: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                insert into players (id, name, rating, cs_rating, lol_rating, lol_lane_1, lol_lane_2, lol_lane_3, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"player_{uuid4()}",
                    name,
                    cs_rating,
                    cs_rating,
                    lol_rating,
                    lane_1,
                    lane_2,
                    lane_3,
                    now_iso(),
                ),
            )

    def update_player_profile(
        self,
        player_id: str,
        name: str,
        cs_rating: int,
        lol_rating: int,
        lane_1: str,
        lane_2: str,
        lane_3: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                update players
                set name = ?, cs_rating = ?, lol_rating = ?, lol_lane_1 = ?, lol_lane_2 = ?, lol_lane_3 = ?
                where id = ?
                """,
                (name, cs_rating, lol_rating, lane_1, lane_2, lane_3, player_id),
            )

    def delete_player(self, player_id: str) -> None:
        with self._conn() as conn:
            conn.execute("delete from players where id = ?", (player_id,))

    def create_match(self, game: str, winner: str, team_a_avg: float, team_b_avg: float) -> str:
        match_id = f"match_{uuid4()}"
        with self._conn() as conn:
            conn.execute(
                """
                insert into matches (id, game, winner, team_a_avg, team_b_avg, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (match_id, game, winner, team_a_avg, team_b_avg, now_iso()),
            )
        return match_id

    def update_player_rating(self, player_id: str, game: str, new_rating: int) -> None:
        col = "cs_rating" if game == "CS" else "lol_rating"
        with self._conn() as conn:
            conn.execute(f"update players set {col} = ? where id = ?", (new_rating, player_id))

    def add_match_players(self, rows: list[dict[str, Any]]) -> None:
        with self._conn() as conn:
            conn.executemany(
                """
                insert into match_players (match_id, player_id, team, role, rating_before, rating_after)
                values (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["match_id"],
                        r["player_id"],
                        r["team"],
                        r.get("role"),
                        r["rating_before"],
                        r["rating_after"],
                    )
                    for r in rows
                ],
            )

    def get_match_players(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("select match_id, player_id, team, role from match_players").fetchall()
        return [dict(r) for r in rows]

    def get_matches(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("select id, game, winner from matches").fetchall()
        return [dict(r) for r in rows]

    def get_recent_matches(self, game: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                select id, game, winner, team_a_avg, team_b_avg, created_at
                from matches
                where game = ?
                order by created_at desc
                limit ?
                """,
                (game, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_match_players_by_match(self, match_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                select match_id, player_id, team, role, rating_before, rating_after
                from match_players where match_id = ?
                """,
                (match_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_game_print(self, title: str, game: str, note: str, image_b64: str, mime_type: str, created_by: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                insert into game_prints (title, game, note, image_b64, mime_type, created_by, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, game, note, image_b64, mime_type, created_by, now_iso()),
            )

    def get_recent_game_prints(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                select id, title, game, note, image_b64, mime_type, created_by, created_at
                from game_prints
                order by created_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_game_print(self, print_id: Any) -> None:
        with self._conn() as conn:
            conn.execute("delete from game_prints where id = ?", (print_id,))


class SupabaseStore(DataStore):
    def __init__(self, client: Any):
        self.client = client

    def is_local(self) -> bool:
        return False

    def load_players(self) -> list[dict[str, Any]]:
        rows = cast(list[dict[str, Any]], self.client.table("players").select("*").execute().data)
        return [normalize_player(r) for r in rows]

    def find_player_by_name(self, name: str) -> dict[str, Any] | None:
        rows = cast(list[dict[str, Any]], self.client.table("players").select("*").eq("name", name).limit(1).execute().data)
        return normalize_player(rows[0]) if rows else None

    def add_player(
        self,
        name: str,
        cs_rating: int,
        lol_rating: int,
        lane_1: str,
        lane_2: str,
        lane_3: str,
    ) -> None:
        payload = {
            "name": name,
            "rating": cs_rating,
            "cs_rating": cs_rating,
            "lol_rating": lol_rating,
            "lol_lane_1": lane_1,
            "lol_lane_2": lane_2,
            "lol_lane_3": lane_3,
        }
        self.client.table("players").insert(payload).execute()

    def update_player_profile(
        self,
        player_id: str,
        name: str,
        cs_rating: int,
        lol_rating: int,
        lane_1: str,
        lane_2: str,
        lane_3: str,
    ) -> None:
        self.client.table("players").update(
            {
                "name": name,
                "cs_rating": cs_rating,
                "lol_rating": lol_rating,
                "lol_lane_1": lane_1,
                "lol_lane_2": lane_2,
                "lol_lane_3": lane_3,
            }
        ).eq("id", player_id).execute()

    def delete_player(self, player_id: str) -> None:
        self.client.table("players").delete().eq("id", player_id).execute()

    def create_match(self, game: str, winner: str, team_a_avg: float, team_b_avg: float) -> str:
        row = (
            self.client.table("matches")
            .insert({"game": game, "winner": winner, "team_a_avg": team_a_avg, "team_b_avg": team_b_avg})
            .execute()
            .data[0]
        )
        return row["id"]

    def update_player_rating(self, player_id: str, game: str, new_rating: int) -> None:
        col = "cs_rating" if game == "CS" else "lol_rating"
        self.client.table("players").update({col: new_rating}).eq("id", player_id).execute()

    def add_match_players(self, rows: list[dict[str, Any]]) -> None:
        self.client.table("match_players").insert(rows).execute()

    def get_match_players(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.client.table("match_players").select("match_id, player_id, team, role").execute().data)

    def get_matches(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.client.table("matches").select("id, game, winner").execute().data)

    def get_recent_matches(self, game: str, limit: int = 20) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self.client.table("matches").select("*").eq("game", game).order("created_at", desc=True).limit(limit).execute().data,
        )

    def get_match_players_by_match(self, match_id: str) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.client.table("match_players").select("*").eq("match_id", match_id).execute().data)

    def add_game_print(self, title: str, game: str, note: str, image_b64: str, mime_type: str, created_by: str) -> None:
        self.client.table("game_prints").insert(
            {
                "title": title,
                "game": game,
                "note": note,
                "image_b64": image_b64,
                "mime_type": mime_type,
                "created_by": created_by,
            }
        ).execute()

    def get_recent_game_prints(self, limit: int = 60) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self.client.table("game_prints").select("*").order("created_at", desc=True).limit(limit).execute().data,
        )

    def delete_game_print(self, print_id: Any) -> None:
        self.client.table("game_prints").delete().eq("id", print_id).execute()


@st.cache_resource
def get_store() -> DataStore:
    mode = st.secrets.get("app", {}).get("data_mode", "local").lower()
    if mode == "supabase":
        if create_client is None:
            st.error("Pacote 'supabase' nao instalado.")
            st.stop()
        cfg = st.secrets.get("supabase")
        if not cfg or not cfg.get("url") or not cfg.get("key"):
            st.error("Config de Supabase ausente em st.secrets['supabase']")
            st.stop()
        return SupabaseStore(create_client(cfg["url"], cfg["key"]))
    return LocalSQLiteStore(LOCAL_DB_PATH)


store = get_store()
inject_theme()
current_user, current_role = ensure_login()


def rating_key(game: str) -> str:
    return "cs_rating" if game == "CS" else "lol_rating"


def lane_score(player: dict[str, Any], lane: str) -> int:
    prefs = [player.get("lol_lane_1"), player.get("lol_lane_2"), player.get("lol_lane_3")]
    if lane == prefs[0]:
        return 3
    if lane == prefs[1]:
        return 2
    if lane == prefs[2]:
        return 1
    return 0


def best_lane_assignment(team: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    best_map: dict[str, dict[str, Any]] = {}
    best_score = -1
    for perm in permutations(team, TEAM_SIZE):
        score = 0
        current: dict[str, dict[str, Any]] = {}
        for lane, player in zip(LANES, perm):
            current[lane] = player
            score += lane_score(player, lane)
        if score > best_score:
            best_score = score
            best_map = current
    return best_map, best_score


def best_cs_split(players: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    key = rating_key("CS")
    best_diff = float("inf")
    best_sets: list[set[int]] = []
    total = sum(int(p[key]) for p in players)
    for combo in combinations(range(len(players)), TEAM_SIZE):
        s = sum(int(players[i][key]) for i in combo)
        diff = abs(2 * s - total)
        if diff < best_diff:
            best_diff = diff
            best_sets = [set(combo)]
        elif diff == best_diff:
            best_sets.append(set(combo))
    pick = random.choice(best_sets)
    ta = [players[i] for i in range(len(players)) if i in pick]
    tb = [players[i] for i in range(len(players)) if i not in pick]
    return ta, tb


def best_lol_match(players: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rkey = rating_key("LoL")
    best_value: tuple[float, float] | None = None
    best_payload = None

    total = sum(int(p[rkey]) for p in players)
    for combo in combinations(range(len(players)), TEAM_SIZE):
        set_a = set(combo)
        team_a = [players[i] for i in range(len(players)) if i in set_a]
        team_b = [players[i] for i in range(len(players)) if i not in set_a]

        sum_a = sum(int(p[rkey]) for p in team_a)
        rating_diff = abs(2 * sum_a - total)

        map_a, pref_a = best_lane_assignment(team_a)
        map_b, pref_b = best_lane_assignment(team_b)
        pref_total = pref_a + pref_b

        objective = (float(rating_diff), -float(pref_total))
        if best_value is None or objective < best_value:
            best_value = objective
            best_payload = (team_a, team_b, map_a, map_b)

    if best_payload is None:
        team_a = players[:TEAM_SIZE]
        team_b = players[TEAM_SIZE:]
        map_a, _ = best_lane_assignment(team_a)
        map_b, _ = best_lane_assignment(team_b)
        return team_a, team_b, map_a, map_b
    return best_payload


def profile_badge(player: dict[str, Any]) -> str:
    lanes = [player.get("lol_lane_1"), player.get("lol_lane_2"), player.get("lol_lane_3")]
    lanes = [x for x in lanes if x]
    txt = ", ".join(lanes) if lanes else "sem lanes"
    return f"CS {player['cs_rating']} | LoL {player['lol_rating']} | {txt}"


def register_match(game: str, team_a: list[dict[str, Any]], team_b: list[dict[str, Any]], winner: str, roles_a: dict[str, dict[str, Any]] | None = None, roles_b: dict[str, dict[str, Any]] | None = None) -> None:
    rkey = rating_key(game)
    avg_a = sum(int(p[rkey]) for p in team_a) / max(1, len(team_a))
    avg_b = sum(int(p[rkey]) for p in team_b) / max(1, len(team_b))
    code = "A" if winner == "Time A" else "B"

    match_id = store.create_match(game=game, winner=code, team_a_avg=round(avg_a, 2), team_b_avg=round(avg_b, 2))

    lane_by_id_a = {}
    lane_by_id_b = {}
    if roles_a:
        lane_by_id_a = {pl["id"]: lane for lane, pl in roles_a.items()}
    if roles_b:
        lane_by_id_b = {pl["id"]: lane for lane, pl in roles_b.items()}

    rows: list[dict[str, Any]] = []
    for p in team_a:
        before = int(p[rkey])
        delta = RATING_DELTA if code == "A" else -RATING_DELTA
        after = max(0, before + delta)
        rows.append(
            {
                "match_id": match_id,
                "player_id": p["id"],
                "team": "A",
                "role": lane_by_id_a.get(p["id"]),
                "rating_before": before,
                "rating_after": after,
            }
        )
        store.update_player_rating(player_id=p["id"], game=game, new_rating=after)

    for p in team_b:
        before = int(p[rkey])
        delta = RATING_DELTA if code == "B" else -RATING_DELTA
        after = max(0, before + delta)
        rows.append(
            {
                "match_id": match_id,
                "player_id": p["id"],
                "team": "B",
                "role": lane_by_id_b.get(p["id"]),
                "rating_before": before,
                "rating_after": after,
            }
        )
        store.update_player_rating(player_id=p["id"], game=game, new_rating=after)

    store.add_match_players(rows)


def game_state_key(game: str, suffix: str) -> str:
    return f"mm_{game.lower()}_{suffix}"


def ensure_mm_state(game: str) -> None:
    for key, default in [
        ("team_a", []),
        ("team_b", []),
        ("selected_ids", []),
        ("roles_a", {}),
        ("roles_b", {}),
    ]:
        sk = game_state_key(game, key)
        if sk not in st.session_state:
            st.session_state[sk] = default


st.sidebar.title("SortedX5")
mode_label = "LOCAL (SQLite)" if store.is_local() else "SUPABASE"
st.sidebar.caption(f"Modo de dados: {mode_label}")
st.sidebar.caption(f"Usuario: {current_user} ({current_role})")
if st.sidebar.button("Sair"):
    for k in ["auth_ok", "auth_user", "auth_role"]:
        st.session_state.pop(k, None)
    _clear_auth_cookie()
    st.rerun()

if current_role == "admin":
    pages = ["Jogadores", "Matchmaking", "Prints", "Ranking", "Historico"]
else:
    pages = ["Matchmaking", "Prints"]

page = st.sidebar.radio("Navegacao", pages)

players = store.load_players()

if page == "Jogadores":
    st.markdown("## Jogadores")
    st.markdown("<div class='sx-sub'>Cadastro com rating separado para CS e LoL + preferencia de lanes.</div>", unsafe_allow_html=True)

    with st.form("add_player_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        name = c1.text_input("Nome")
        cs = c2.number_input("CS Rating", min_value=0, value=DEFAULT_RATING, step=25)
        lol = c3.number_input("LoL Rating", min_value=0, value=DEFAULT_RATING, step=25)

        l1, l2, l3 = st.columns(3)
        lane_1 = l1.selectbox("Lane favorita #1", [""] + LANES)
        lane_2 = l2.selectbox("Lane favorita #2", [""] + LANES)
        lane_3 = l3.selectbox("Lane favorita #3", [""] + LANES)

        submit = st.form_submit_button("Adicionar jogador")

    if submit:
        clean = name.strip()
        if not clean:
            st.warning("Informe um nome.")
        elif store.find_player_by_name(clean):
            st.error("Jogador ja existe.")
        else:
            store.add_player(clean, int(cs), int(lol), lane_1, lane_2, lane_3)
            st.success("Jogador cadastrado.")
            st.rerun()

    st.markdown("### Perfis")
    if not players:
        st.info("Nenhum jogador cadastrado.")
    else:
        for p in players:
            with st.expander(f"{p['name']} - {profile_badge(p)}"):
                n1, e1, e2 = st.columns([2, 1, 1])
                name_new = n1.text_input("Nome", value=str(p["name"]), key=f"name_{p['id']}")
                cs_new = e1.number_input("CS", min_value=0, value=int(p["cs_rating"]), step=25, key=f"cs_{p['id']}")
                lol_new = e2.number_input("LoL", min_value=0, value=int(p["lol_rating"]), step=25, key=f"lol_{p['id']}")
                ln1, ln2, ln3 = st.columns(3)
                lane1 = ln1.selectbox("Lane #1", [""] + LANES, index=([""] + LANES).index(p.get("lol_lane_1", "") if p.get("lol_lane_1", "") in LANES else ""), key=f"l1_{p['id']}")
                lane2 = ln2.selectbox("Lane #2", [""] + LANES, index=([""] + LANES).index(p.get("lol_lane_2", "") if p.get("lol_lane_2", "") in LANES else ""), key=f"l2_{p['id']}")
                lane3 = ln3.selectbox("Lane #3", [""] + LANES, index=([""] + LANES).index(p.get("lol_lane_3", "") if p.get("lol_lane_3", "") in LANES else ""), key=f"l3_{p['id']}")

                action_left, action_right = st.columns(2)
                if action_left.button("Salvar alteracoes", key=f"save_{p['id']}"):
                    clean_name = name_new.strip()
                    if not clean_name:
                        st.warning("Nome nao pode ficar vazio.")
                    else:
                        duplicate = any(
                            other["id"] != p["id"] and str(other["name"]).strip().lower() == clean_name.lower()
                            for other in players
                        )
                        if duplicate:
                            st.error("Ja existe jogador com esse nome.")
                        else:
                            store.update_player_profile(p["id"], clean_name, int(cs_new), int(lol_new), lane1, lane2, lane3)
                            st.success("Perfil atualizado.")
                            st.rerun()

                confirm_delete = st.checkbox("Confirmar exclusao", key=f"confirm_delete_{p['id']}")
                if action_right.button("Excluir jogador", key=f"delete_{p['id']}"):
                    if not confirm_delete:
                        st.warning("Marque 'Confirmar exclusao' para remover o jogador.")
                    else:
                        store.delete_player(p["id"])
                        st.success("Jogador removido.")
                        st.rerun()

elif page == "Matchmaking":
    st.markdown("## Matchmaking")
    st.markdown("<div class='sx-sub'>Dois modos: CS (balance por rating) e LoL (balance + lanes preferidas).</div>", unsafe_allow_html=True)

    game = st.radio("Modo", GAME_OPTIONS, horizontal=True)
    ensure_mm_state(game)

    if len(players) < 10:
        st.warning(f"Cadastre pelo menos 10 jogadores. Atual: {len(players)}")
        st.stop()

    names = [p["name"] for p in players]
    selected_names = st.multiselect(
        "Selecione 10 jogadores",
        options=names,
        max_selections=10,
        key=game_state_key(game, "selected_names"),
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("Sortear", key=game_state_key(game, "draw")) and len(selected_names) == 10:
        chosen = [p for p in players if p["name"] in selected_names]
        if game == "CS":
            ta, tb = best_cs_split(chosen)
            st.session_state[game_state_key(game, "roles_a")] = {}
            st.session_state[game_state_key(game, "roles_b")] = {}
        else:
            ta, tb, ra, rb = best_lol_match(chosen)
            st.session_state[game_state_key(game, "roles_a")] = ra
            st.session_state[game_state_key(game, "roles_b")] = rb
        st.session_state[game_state_key(game, "team_a")] = ta
        st.session_state[game_state_key(game, "team_b")] = tb
        st.session_state[game_state_key(game, "selected_ids")] = [p["id"] for p in chosen]
        st.rerun()

    if c2.button("Sortear novamente", key=game_state_key(game, "redraw")):
        selected_ids = st.session_state[game_state_key(game, "selected_ids")]
        chosen = [p for p in players if p["id"] in selected_ids]
        if len(chosen) == 10:
            if game == "CS":
                ta, tb = best_cs_split(chosen)
                st.session_state[game_state_key(game, "roles_a")] = {}
                st.session_state[game_state_key(game, "roles_b")] = {}
            else:
                ta, tb, ra, rb = best_lol_match(chosen)
                st.session_state[game_state_key(game, "roles_a")] = ra
                st.session_state[game_state_key(game, "roles_b")] = rb
            st.session_state[game_state_key(game, "team_a")] = ta
            st.session_state[game_state_key(game, "team_b")] = tb
            st.rerun()

    st.markdown("<span class='sx-kpi'>CS usa cs_rating</span><span class='sx-kpi'>LoL usa lol_rating + lanes</span>", unsafe_allow_html=True)

    team_a = st.session_state[game_state_key(game, "team_a")]
    team_b = st.session_state[game_state_key(game, "team_b")]
    roles_a = st.session_state[game_state_key(game, "roles_a")]
    roles_b = st.session_state[game_state_key(game, "roles_b")]

    if team_a and team_b:
        rkey = rating_key(game)
        avg_a = sum(int(p[rkey]) for p in team_a) / max(1, len(team_a))
        avg_b = sum(int(p[rkey]) for p in team_b) / max(1, len(team_b))

        left, right = st.columns(2)
        with left:
            st.markdown(f"### Time A - media {avg_a:.0f}")
            for p in team_a:
                role = ""
                if roles_a:
                    role = next((lane for lane, pl in roles_a.items() if pl["id"] == p["id"]), "")
                st.markdown(f"- **{p['name']}** ({p[rkey]}) {f'[{role}]' if role else ''}")
        with right:
            st.markdown(f"### Time B - media {avg_b:.0f}")
            for p in team_b:
                role = ""
                if roles_b:
                    role = next((lane for lane, pl in roles_b.items() if pl["id"] == p["id"]), "")
                st.markdown(f"- **{p['name']}** ({p[rkey]}) {f'[{role}]' if role else ''}")

        st.caption(f"Diferenca de media: {abs(avg_a - avg_b):.1f}")

        if current_role == "admin":
            st.divider()
            winner = st.radio("Quem venceu?", ["Time A", "Time B"], horizontal=True, key=game_state_key(game, "winner"))
            if st.button("Registrar partida", key=game_state_key(game, "register")):
                register_match(game, team_a, team_b, winner, roles_a if game == "LoL" else None, roles_b if game == "LoL" else None)
                st.success("Partida registrada e ratings atualizados.")
                for sfx in ["team_a", "team_b", "selected_ids", "roles_a", "roles_b"]:
                    st.session_state[game_state_key(game, sfx)] = [] if sfx in ("team_a", "team_b", "selected_ids") else {}
                st.rerun()
        else:
            st.info("Perfil padrao pode apenas selecionar jogadores e sortear times.")

elif page == "Ranking":
    st.markdown("## Ranking")
    game = st.radio("Jogo", GAME_OPTIONS, horizontal=True)
    rkey = rating_key(game)

    matches = store.get_matches()
    mp_data = store.get_match_players()
    winner_map = {m["id"]: (m.get("winner"), m.get("game", "CS")) for m in matches}

    stats: dict[str, dict[str, int]] = {}
    for row in mp_data:
        match_info = winner_map.get(row["match_id"])
        if not match_info:
            continue
        winner, match_game = match_info
        if (match_game or "CS") != game:
            continue
        pid = row["player_id"]
        if pid not in stats:
            stats[pid] = {"games": 0, "wins": 0}
        stats[pid]["games"] += 1
        if row["team"] == winner:
            stats[pid]["wins"] += 1

    rows = []
    for idx, p in enumerate(sorted(players, key=lambda x: int(x[rkey]), reverse=True), 1):
        s = stats.get(p["id"], {"games": 0, "wins": 0})
        wr = (s["wins"] / s["games"] * 100) if s["games"] else 0
        rows.append(
            {
                "#": idx,
                "Jogador": p["name"],
                "Rating": int(p[rkey]),
                "Partidas": s["games"],
                "Vitorias": s["wins"],
                "WR": f"{wr:.0f}%",
            }
        )

    st.dataframe(rows, hide_index=True, use_container_width=True)

elif page == "Prints":
    st.markdown("## Repositorio de Prints")
    st.markdown("<div class='sx-sub'>Galeria compartilhada para guardar momentos das partidas.</div>", unsafe_allow_html=True)

    if current_role == "admin":
        with st.form("add_print_form", clear_on_submit=True):
            t1, t2 = st.columns([2, 1])
            print_title = t1.text_input("Titulo")
            print_game = t2.selectbox("Jogo", ["Geral"] + GAME_OPTIONS)
            print_note = st.text_area("Descricao (opcional)", max_chars=500)
            print_file = st.file_uploader("Arquivo de imagem", type=["png", "jpg", "jpeg", "webp"])
            publish = st.form_submit_button("Publicar print")

        if publish:
            clean_title = print_title.strip()
            if not clean_title:
                st.warning("Informe um titulo para o print.")
            elif print_file is None:
                st.warning("Selecione uma imagem.")
            else:
                raw = print_file.getvalue()
                if not raw:
                    st.warning("Arquivo vazio.")
                elif len(raw) > 4 * 1024 * 1024:
                    st.warning("Imagem muito grande. Limite de 4MB por print.")
                else:
                    mime = str(print_file.type or "image/png")
                    encoded = base64.b64encode(raw).decode("ascii")
                    store.add_game_print(
                        title=clean_title,
                        game=print_game,
                        note=print_note.strip(),
                        image_b64=encoded,
                        mime_type=mime,
                        created_by=current_user,
                    )
                    st.success("Print publicado.")
                    st.rerun()
    else:
        st.info("Somente admin pode publicar/remover prints. Todos podem visualizar.")

    prints = store.get_recent_game_prints(limit=80)
    if not prints:
        st.info("Nenhum print publicado ainda.")
    else:
        for item in prints:
            title = item.get("title") or "Sem titulo"
            game = item.get("game") or "Geral"
            who = item.get("created_by") or "desconhecido"
            ts = str(item.get("created_at") or "").replace("T", " ")[:16]
            with st.expander(f"{game} | {title} | {ts}"):
                payload = item.get("image_b64") or ""
                mime = item.get("mime_type") or "image/png"
                try:
                    st.image(base64.b64decode(payload), caption=f"por {who}", use_container_width=True)
                except Exception:
                    st.error("Nao foi possivel renderizar esta imagem.")

                note = str(item.get("note") or "").strip()
                if note:
                    st.write(note)

                if current_role == "admin":
                    if st.button("Remover print", key=f"del_print_{item['id']}"):
                        store.delete_game_print(item["id"])
                        st.success("Print removido.")
                        st.rerun()

elif page == "Historico":
    st.markdown("## Historico")
    game = st.radio("Jogo", GAME_OPTIONS, horizontal=True)
    matches = store.get_recent_matches(game=game, limit=20)

    if not matches:
        st.info("Sem partidas registradas para este jogo.")
    else:
        id_to_name = {p["id"]: p["name"] for p in players}
        for m in matches:
            rows = store.get_match_players_by_match(m["id"])
            ta, tb = [], []
            for r in rows:
                name = id_to_name.get(r["player_id"], "?")
                delta = int(r["rating_after"]) - int(r["rating_before"])
                sign = "+" if delta >= 0 else ""
                role = f" [{r['role']}]" if r.get("role") else ""
                txt = f"{name}{role} ({sign}{delta})"
                if r["team"] == "A":
                    ta.append(txt)
                else:
                    tb.append(txt)

            win = "Time A" if m["winner"] == "A" else "Time B"
            ts = str(m["created_at"]).replace("T", " ")[:16]
            with st.expander(f"{game} | {win} venceu | {ts}"):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Time A** (media {float(m['team_a_avg']):.0f})")
                for x in ta:
                    c1.write(f"- {x}")
                c2.markdown(f"**Time B** (media {float(m['team_b_avg']):.0f})")
                for x in tb:
                    c2.write(f"- {x}")
