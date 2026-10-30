import asyncio
from datetime import datetime, timezone
import json
import sys
from typing import Any
import psycopg
from psycopg.rows import dict_row

from .config import get_database_url, normalize_clan_tag

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

LEAGUE_COLUMNS = """
    id,
    clan_tag,
    clan_name,
    user_id,
    user_email,
    lineup_size,
    opted_in_tags,
    schedule_by_day,
    opponents_by_day,
    updated_at
"""

ACCOUNT_COLUMNS = """
    id,
    user_id,
    player_tag,
    player_name,
    town_hall_level,
    trophies,
    role,
    clan_tag,
    clan_name,
    clan_badge_url,
    is_active,
    created_at,
    updated_at
"""


class LastAccountError(ValueError):
    """Raised when a user attempts to delete their last remaining in-game account."""



def _serialize_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return value


def format_league_row(row: dict[str, Any]) -> dict[str, Any]:
    """Format a cwl_leagues row for JSON responses."""
    return {
        "id": row["id"],
        "clan_tag": row["clan_tag"],
        "clan_name": row["clan_name"],
        "user_id": row["user_id"],
        "user_email": row.get("user_email"),
        "lineup_size": int(row["lineup_size"]),
        "opted_in_tags": row["opted_in_tags"] if row["opted_in_tags"] is not None else [],
        "schedule_by_day": row["schedule_by_day"] if row["schedule_by_day"] is not None else {},
        "opponents_by_day": row["opponents_by_day"] if row["opponents_by_day"] is not None else {},
        "updated_at": _serialize_timestamp(row["updated_at"]),
    }


def format_account_row(row: dict[str, Any]) -> dict[str, Any]:
    """Format a user_ingame_accounts row for JSON responses (both snake_case and camelCase)."""
    created_at = _serialize_timestamp(row.get("created_at"))
    updated_at = _serialize_timestamp(row.get("updated_at"))
    th_level = int(row.get("town_hall_level") if row.get("town_hall_level") is not None else 16)
    trophies = int(row.get("trophies") if row.get("trophies") is not None else 0)
    role = row.get("role") or "member"
    is_active = bool(row.get("is_active", False))

    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "player_tag": row["player_tag"],
        "player_name": row["player_name"],
        "town_hall_level": th_level,
        "trophies": trophies,
        "role": role,
        "clan_tag": row["clan_tag"],
        "clan_name": row["clan_name"],
        "clan_badge_url": row.get("clan_badge_url"),
        "is_active": is_active,
        "created_at": created_at,
        "updated_at": updated_at,
        # camelCase aliases for frontend convenience
        "userId": row["user_id"],
        "playerTag": row["player_tag"],
        "playerName": row["player_name"],
        "townHallLevel": th_level,
        "clanTag": row["clan_tag"],
        "clanName": row["clan_name"],
        "clanBadgeUrl": row.get("clan_badge_url"),
        "isActive": is_active,
        "createdAt": created_at,
        "updatedAt": updated_at,
    }


async def get_async_connection(unpooled: bool = False) -> psycopg.AsyncConnection:
    conn_str = get_database_url(unpooled=unpooled)
    return await psycopg.AsyncConnection.connect(conn_str, row_factory=dict_row, autocommit=True)


async def ensure_cwl_leagues_table() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS public.cwl_leagues (
        id text NOT NULL PRIMARY KEY,
        clan_tag text NOT NULL,
        clan_name text NOT NULL,
        user_id text NOT NULL,
        user_email text,
        lineup_size integer NOT NULL DEFAULT 15,
        opted_in_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
        schedule_by_day jsonb NOT NULL DEFAULT '{}'::jsonb,
        opponents_by_day jsonb NOT NULL DEFAULT '{}'::jsonb,
        updated_at timestamp with time zone NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS public.user_ingame_accounts (
        id text NOT NULL PRIMARY KEY,
        user_id text NOT NULL,
        player_tag text NOT NULL,
        player_name text NOT NULL,
        town_hall_level integer NOT NULL DEFAULT 16,
        trophies integer NOT NULL DEFAULT 0,
        role text DEFAULT 'member'::text,
        clan_tag text NOT NULL,
        clan_name text NOT NULL,
        clan_badge_url text,
        is_active boolean NOT NULL DEFAULT false,
        created_at timestamp with time zone NOT NULL DEFAULT now(),
        updated_at timestamp with time zone NOT NULL DEFAULT now()
    );
    """
    async with await get_async_connection(unpooled=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql)


async def check_db_status() -> dict[str, Any]:
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT current_database() AS database, now() AS now")
            row = await cur.fetchone()
            return {
                "connected": True,
                "database": row["database"],
                "now": _serialize_timestamp(row["now"]),
            }


async def list_leagues(clan_tag: str | None = None) -> list[dict[str, Any]]:
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            if clan_tag:
                normalized = normalize_clan_tag(clan_tag)
                await cur.execute(
                    f"""
                    SELECT {LEAGUE_COLUMNS}
                    FROM public.cwl_leagues
                    WHERE clan_tag = %s
                    ORDER BY updated_at DESC
                    """,
                    (normalized,),
                )
            else:
                await cur.execute(
                    f"""
                    SELECT {LEAGUE_COLUMNS}
                    FROM public.cwl_leagues
                    ORDER BY updated_at DESC
                    """
                )
            rows = await cur.fetchall()
            return [format_league_row(r) for r in rows]


async def get_league_by_clan_tag(clan_tag: str) -> dict[str, Any] | None:
    normalized = normalize_clan_tag(clan_tag)
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {LEAGUE_COLUMNS}
                FROM public.cwl_leagues
                WHERE clan_tag = %s
                LIMIT 1
                """,
                (normalized,),
            )
            row = await cur.fetchone()
            return format_league_row(row) if row else None


async def upsert_league(
    *,
    clan_tag: str,
    clan_name: str,
    user_id: str,
    user_email: str | None = None,
    lineup_size: int = 15,
    opted_in_tags: list[str] | None = None,
    schedule_by_day: dict[str, list[str]] | None = None,
    opponents_by_day: dict[str, str] | None = None,
    league_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_tag = normalize_clan_tag(clan_tag)
    resolved_id = normalize_clan_tag(league_id) if league_id else normalized_tag
    resolved_name = (clan_name or normalized_tag).strip()
    resolved_lineup_size = int(lineup_size)
    if resolved_lineup_size not in (15, 25, 30):
        raise ValueError("lineup_size must be one of 15, 25, or 30")

    opted_json = json.dumps(opted_in_tags if opted_in_tags is not None else [])
    schedule_json = json.dumps(
        {str(k): v for k, v in (schedule_by_day or {}).items()}
    )
    opponents_json = json.dumps(
        {str(k): v for k, v in (opponents_by_day or {}).items()}
    )

    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO public.cwl_leagues (
                    id,
                    clan_tag,
                    clan_name,
                    user_id,
                    user_email,
                    lineup_size,
                    opted_in_tags,
                    schedule_by_day,
                    opponents_by_day,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (id) DO UPDATE SET
                    clan_tag = EXCLUDED.clan_tag,
                    clan_name = EXCLUDED.clan_name,
                    user_id = EXCLUDED.user_id,
                    user_email = EXCLUDED.user_email,
                    lineup_size = EXCLUDED.lineup_size,
                    opted_in_tags = EXCLUDED.opted_in_tags,
                    schedule_by_day = EXCLUDED.schedule_by_day,
                    opponents_by_day = EXCLUDED.opponents_by_day,
                    updated_at = now()
                RETURNING
                    {LEAGUE_COLUMNS},
                    pg_current_xact_id()::text AS txid
                """,
                (
                    resolved_id,
                    normalized_tag,
                    resolved_name,
                    user_id,
                    user_email,
                    resolved_lineup_size,
                    opted_json,
                    schedule_json,
                    opponents_json,
                ),
            )
            row = await cur.fetchone()
            return format_league_row(row), str(row["txid"])


async def update_league_day(
    clan_tag: str,
    day: int | str,
    player_tags: list[str],
) -> tuple[dict[str, Any], str] | None:
    day_int = int(day)
    if day_int < 1 or day_int > 7:
        raise ValueError("day must be between 1 and 7")
    day_key = str(day_int)
    normalized_tag = normalize_clan_tag(clan_tag)
    players_json = json.dumps(list(player_tags))

    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE public.cwl_leagues
                SET
                    schedule_by_day = jsonb_set(
                        COALESCE(schedule_by_day, '{{}}'::jsonb),
                        ARRAY[%s::text],
                        %s::jsonb,
                        true
                    ),
                    updated_at = now()
                WHERE clan_tag = %s
                RETURNING
                    {LEAGUE_COLUMNS},
                    pg_current_xact_id()::text AS txid
                """,
                (day_key, players_json, normalized_tag),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return format_league_row(row), str(row["txid"])


async def delete_league_by_clan_tag(clan_tag: str) -> dict[str, Any] | None:
    normalized_tag = normalize_clan_tag(clan_tag)
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM public.cwl_leagues
                WHERE clan_tag = %s
                RETURNING id, clan_tag, pg_current_xact_id()::text AS txid
                """,
                (normalized_tag,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "clan_tag": row["clan_tag"],
                "txid": str(row["txid"]),
            }


async def list_user_accounts(user_id: str) -> list[dict[str, Any]]:
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            rows = await cur.fetchall()
            return [format_account_row(r) for r in rows]


async def upsert_user_accounts(
    user_id: str,
    accounts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if not accounts:
        raise ValueError("At least one in-game account is required")

    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            existing_rows = await cur.fetchall()
            existing_by_tag = {r["player_tag"]: r for r in existing_rows}
            current_active_tag = next(
                (r["player_tag"] for r in existing_rows if r.get("is_active")),
                None,
            )

            normalized_items: list[dict[str, Any]] = []
            explicit_active_tag: str | None = None

            for idx, item in enumerate(accounts):
                raw_player_tag = (
                    item.get("playerTag")
                    or item.get("player_tag")
                    or item.get("tag")
                    or ""
                )
                if not str(raw_player_tag).strip():
                    raise ValueError(f"playerTag is required for account at index {idx}")
                player_tag = normalize_clan_tag(str(raw_player_tag))

                raw_clan_tag = (
                    item.get("clanTag")
                    or item.get("clan_tag")
                    or (item.get("clan") or {}).get("tag")
                    if isinstance(item.get("clan"), dict)
                    else (item.get("clanTag") or item.get("clan_tag") or "")
                )
                if not str(raw_clan_tag or "").strip():
                    # Fall back to existing clan_tag for this player if already linked
                    existing_acct = existing_by_tag.get(player_tag)
                    if existing_acct and existing_acct.get("clan_tag"):
                        raw_clan_tag = existing_acct["clan_tag"]
                    else:
                        raise ValueError(f"clanTag is required for player {player_tag}")
                clan_tag = normalize_clan_tag(str(raw_clan_tag))

                player_name = str(
                    item.get("playerName")
                    or item.get("player_name")
                    or item.get("name")
                    or existing_by_tag.get(player_tag, {}).get("player_name")
                    or player_tag
                ).strip()

                clan_obj = item.get("clan") if isinstance(item.get("clan"), dict) else {}
                clan_name = str(
                    item.get("clanName")
                    or item.get("clan_name")
                    or clan_obj.get("name")
                    or existing_by_tag.get(player_tag, {}).get("clan_name")
                    or clan_tag
                ).strip()

                badge_urls = (
                    clan_obj.get("badgeUrls")
                    if isinstance(clan_obj.get("badgeUrls"), dict)
                    else {}
                )
                clan_badge_url = (
                    item.get("clanBadgeUrl")
                    or item.get("clan_badge_url")
                    or badge_urls.get("medium")
                    or badge_urls.get("small")
                    or badge_urls.get("large")
                    or existing_by_tag.get(player_tag, {}).get("clan_badge_url")
                )

                th_raw = (
                    item.get("townHallLevel")
                    if item.get("townHallLevel") is not None
                    else item.get("town_hall_level")
                )
                if th_raw is None:
                    th_raw = existing_by_tag.get(player_tag, {}).get("town_hall_level", 16)
                town_hall_level = int(th_raw)

                trophies_raw = item.get("trophies")
                if trophies_raw is None:
                    trophies_raw = existing_by_tag.get(player_tag, {}).get("trophies", 0)
                trophies = int(trophies_raw)

                role = str(
                    item.get("role")
                    or existing_by_tag.get(player_tag, {}).get("role")
                    or "member"
                ).strip()

                req_active = (
                    item.get("isActive")
                    if item.get("isActive") is not None
                    else item.get("is_active")
                )
                if req_active is True and explicit_active_tag is None:
                    explicit_active_tag = player_tag

                existing_id = existing_by_tag.get(player_tag, {}).get("id")
                row_id = str(item.get("id") or existing_id or f"{user_id}:{player_tag}")

                normalized_items.append(
                    {
                        "id": row_id,
                        "user_id": user_id,
                        "player_tag": player_tag,
                        "player_name": player_name,
                        "town_hall_level": town_hall_level,
                        "trophies": trophies,
                        "role": role,
                        "clan_tag": clan_tag,
                        "clan_name": clan_name,
                        "clan_badge_url": clan_badge_url,
                    }
                )

            target_active_tag = (
                explicit_active_tag
                or current_active_tag
                or normalized_items[0]["player_tag"]
            )

            last_txid = "0"
            for acct in normalized_items:
                is_active = acct["player_tag"] == target_active_tag
                await cur.execute(
                    f"""
                    INSERT INTO public.user_ingame_accounts (
                        id,
                        user_id,
                        player_tag,
                        player_name,
                        town_hall_level,
                        trophies,
                        role,
                        clan_tag,
                        clan_name,
                        clan_badge_url,
                        is_active,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        player_tag = EXCLUDED.player_tag,
                        player_name = EXCLUDED.player_name,
                        town_hall_level = EXCLUDED.town_hall_level,
                        trophies = EXCLUDED.trophies,
                        role = EXCLUDED.role,
                        clan_tag = EXCLUDED.clan_tag,
                        clan_name = EXCLUDED.clan_name,
                        clan_badge_url = COALESCE(EXCLUDED.clan_badge_url, public.user_ingame_accounts.clan_badge_url),
                        is_active = EXCLUDED.is_active,
                        updated_at = now()
                    RETURNING
                        {ACCOUNT_COLUMNS},
                        pg_current_xact_id()::text AS txid
                    """,
                    (
                        acct["id"],
                        acct["user_id"],
                        acct["player_tag"],
                        acct["player_name"],
                        acct["town_hall_level"],
                        acct["trophies"],
                        acct["role"],
                        acct["clan_tag"],
                        acct["clan_name"],
                        acct["clan_badge_url"],
                        is_active,
                    ),
                )
                row = await cur.fetchone()
                last_txid = str(row["txid"])

            # Ensure exactly target_active_tag is active across all user accounts
            await cur.execute(
                f"""
                UPDATE public.user_ingame_accounts
                SET is_active = (player_tag = %s)
                WHERE user_id = %s
                RETURNING
                    {ACCOUNT_COLUMNS},
                    pg_current_xact_id()::text AS txid
                """,
                (target_active_tag, user_id),
            )
            updated_rows = await cur.fetchall()
            if updated_rows:
                last_txid = str(updated_rows[0]["txid"])

            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            final_rows = await cur.fetchall()
            return [format_account_row(r) for r in final_rows], last_txid


async def activate_user_account(
    user_id: str,
    player_tag: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
    normalized_tag = normalize_clan_tag(player_tag)
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1
                FROM public.user_ingame_accounts
                WHERE user_id = %s AND player_tag = %s
                LIMIT 1
                """,
                (user_id, normalized_tag),
            )
            exists = await cur.fetchone()
            if not exists:
                return None

            await cur.execute(
                f"""
                UPDATE public.user_ingame_accounts
                SET
                    is_active = (player_tag = %s),
                    updated_at = CASE WHEN player_tag = %s THEN now() ELSE updated_at END
                WHERE user_id = %s
                RETURNING
                    {ACCOUNT_COLUMNS},
                    pg_current_xact_id()::text AS txid
                """,
                (normalized_tag, normalized_tag, user_id),
            )
            rows = await cur.fetchall()
            if not rows:
                return None

            txid = str(rows[0]["txid"])
            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            ordered_rows = await cur.fetchall()
            formatted = [format_account_row(r) for r in ordered_rows]
            active_acct = next(
                (a for a in formatted if a["player_tag"] == normalized_tag),
                formatted[0],
            )
            return active_acct, formatted, txid


async def update_user_account_clan(
    user_id: str,
    player_tag: str,
    *,
    clan_tag: str,
    clan_name: str | None = None,
    clan_badge_url: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
    normalized_player_tag = normalize_clan_tag(player_tag)
    normalized_clan_tag = normalize_clan_tag(clan_tag)
    resolved_clan_name = (clan_name or normalized_clan_tag).strip()

    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE public.user_ingame_accounts
                SET
                    clan_tag = %s,
                    clan_name = %s,
                    clan_badge_url = COALESCE(%s, clan_badge_url),
                    updated_at = now()
                WHERE user_id = %s AND player_tag = %s
                RETURNING
                    {ACCOUNT_COLUMNS},
                    pg_current_xact_id()::text AS txid
                """,
                (
                    normalized_clan_tag,
                    resolved_clan_name,
                    clan_badge_url,
                    user_id,
                    normalized_player_tag,
                ),
            )
            row = await cur.fetchone()
            if not row:
                return None

            txid = str(row["txid"])
            updated_acct = format_account_row(row)

            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            all_rows = await cur.fetchall()
            return updated_acct, [format_account_row(r) for r in all_rows], txid


async def update_user_account_role(
    user_id: str,
    player_tag: str,
    *,
    role: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
    normalized_player_tag = normalize_clan_tag(player_tag)
    resolved_role = (role or "member").strip()
    if not resolved_role:
        raise ValueError("role is required")

    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE public.user_ingame_accounts
                SET
                    role = %s,
                    updated_at = now()
                WHERE user_id = %s AND player_tag = %s
                RETURNING
                    {ACCOUNT_COLUMNS},
                    pg_current_xact_id()::text AS txid
                """,
                (
                    resolved_role,
                    user_id,
                    normalized_player_tag,
                ),
            )
            row = await cur.fetchone()
            if not row:
                return None

            txid = str(row["txid"])
            updated_acct = format_account_row(row)

            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            all_rows = await cur.fetchall()
            return updated_acct, [format_account_row(r) for r in all_rows], txid


async def delete_user_account(
    user_id: str,
    player_tag: str,
) -> dict[str, Any] | None:
    normalized_player_tag = normalize_clan_tag(player_tag)
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            existing_rows = await cur.fetchall()
            total = len(existing_rows)

            if total <= 1:
                raise LastAccountError(
                    "Cannot remove your last in-game account. Every user must have at least 1 linked in-game player."
                )

            target_row = next(
                (r for r in existing_rows if r["player_tag"] == normalized_player_tag),
                None,
            )
            if not target_row:
                return None

            await cur.execute(
                """
                DELETE FROM public.user_ingame_accounts
                WHERE user_id = %s AND player_tag = %s
                RETURNING id, player_tag, is_active, pg_current_xact_id()::text AS txid
                """,
                (user_id, normalized_player_tag),
            )
            deleted = await cur.fetchone()
            if not deleted:
                return None

            txid = str(deleted["txid"])

            # If we deleted the active account, promote the next remaining account to is_active = true
            if deleted.get("is_active"):
                remaining_candidates = [
                    r for r in existing_rows if r["player_tag"] != normalized_player_tag
                ]
                if remaining_candidates:
                    next_active_tag = remaining_candidates[0]["player_tag"]
                    await cur.execute(
                        """
                        UPDATE public.user_ingame_accounts
                        SET
                            is_active = (player_tag = %s),
                            updated_at = CASE WHEN player_tag = %s THEN now() ELSE updated_at END
                        WHERE user_id = %s
                        RETURNING pg_current_xact_id()::text AS txid
                        """,
                        (next_active_tag, next_active_tag, user_id),
                    )
                    promoted = await cur.fetchone()
                    if promoted:
                        txid = str(promoted["txid"])

            await cur.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM public.user_ingame_accounts
                WHERE user_id = %s
                ORDER BY is_active DESC, created_at ASC
                """,
                (user_id,),
            )
            remaining_rows = await cur.fetchall()
            formatted_remaining = [format_account_row(r) for r in remaining_rows]
            active_account = next(
                (a for a in formatted_remaining if a["is_active"]),
                formatted_remaining[0] if formatted_remaining else None,
            )

            return {
                "id": deleted["id"],
                "player_tag": deleted["player_tag"],
                "playerTag": deleted["player_tag"],
                "txid": txid,
                "accounts": formatted_remaining,
                "activeAccount": active_account,
            }

