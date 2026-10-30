from typing import Any
from urllib.parse import quote
import httpx
from fastapi import HTTPException

from .config import get_coc_api_base_url, get_coc_api_token, normalize_clan_tag


def encode_clan_tag(clan_tag: str) -> str:
    """Normalize a clan or player tag to `#TAG` and URL-encode it as `%23TAG`."""
    normalized = normalize_clan_tag(clan_tag)
    return quote(normalized, safe="")


encode_player_tag = encode_clan_tag


def format_coc_player(raw: dict[str, Any], fallback_clan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a Clash of Clans player payload with both camelCase and snake_case fields."""
    clan = raw.get("clan") if isinstance(raw.get("clan"), dict) else (fallback_clan or {})
    badge_urls = clan.get("badgeUrls") if isinstance(clan.get("badgeUrls"), dict) else {}
    badge_url = (
        raw.get("clanBadgeUrl")
        or raw.get("clan_badge_url")
        or badge_urls.get("medium")
        or badge_urls.get("small")
        or badge_urls.get("large")
    )
    tag = raw.get("tag") or raw.get("playerTag") or raw.get("player_tag") or ""
    name = raw.get("name") or raw.get("playerName") or raw.get("player_name") or ""
    th_level = int(raw.get("townHallLevel") or raw.get("town_hall_level") or 16)
    trophies = int(raw.get("trophies") or 0)
    role = raw.get("role") or "member"
    clan_tag = clan.get("tag") or raw.get("clanTag") or raw.get("clan_tag") or ""
    clan_name = clan.get("name") or raw.get("clanName") or raw.get("clan_name") or ""

    enriched = dict(raw)
    enriched.update(
        {
            "tag": tag,
            "name": name,
            "townHallLevel": th_level,
            "trophies": trophies,
            "role": role,
            "playerTag": tag,
            "player_tag": tag,
            "playerName": name,
            "player_name": name,
            "town_hall_level": th_level,
            "clanTag": clan_tag,
            "clan_tag": clan_tag,
            "clanName": clan_name,
            "clan_name": clan_name,
            "clanBadgeUrl": badge_url,
            "clan_badge_url": badge_url,
        }
    )
    if clan_tag and "clan" not in enriched:
        enriched["clan"] = {
            "tag": clan_tag,
            "name": clan_name,
            "badgeUrls": badge_urls,
        }
    return enriched


async def _coc_request(path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    token = get_coc_api_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="COC_API_TOKEN is not configured on the server",
        )

    url = f"{get_coc_api_base_url()}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    clean_params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=clean_params)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Clash of Clans API: {exc}",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text}

    return response.status_code, payload


async def search_clans(
    *,
    name: str | None = None,
    warFrequency: str | None = None,
    minClanLevel: int | None = None,
    minMembers: int | None = None,
    maxMembers: int | None = None,
    minClanPoints: int | None = None,
    locationId: int | str | None = None,
    limit: int | None = None,
    after: str | None = None,
    before: str | None = None,
    labelIds: str | None = None,
) -> tuple[int, Any]:
    if name is not None and len(name.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Clan search 'name' parameter must be at least 3 characters",
        )
    params = {
        "name": name.strip() if name else None,
        "warFrequency": warFrequency,
        "minClanLevel": minClanLevel,
        "minMembers": minMembers,
        "maxMembers": maxMembers,
        "minClanPoints": minClanPoints,
        "locationId": locationId,
        "limit": limit,
        "after": after,
        "before": before,
        "labelIds": labelIds,
    }
    if not any(v is not None for v in params.values()):
        raise HTTPException(
            status_code=400,
            detail="At least one search filter (e.g. 'name' with min 3 chars) is required",
        )
    return await _coc_request("/clans", params=params)


async def get_clan_profile(clan_tag: str) -> tuple[int, Any]:
    encoded = encode_clan_tag(clan_tag)
    return await _coc_request(f"/clans/{encoded}")


async def get_clan_members(
    clan_tag: str,
    *,
    limit: int | None = None,
    after: str | None = None,
    before: str | None = None,
) -> tuple[int, Any]:
    encoded = encode_clan_tag(clan_tag)
    params = {"limit": limit, "after": after, "before": before}
    return await _coc_request(f"/clans/{encoded}/members", params=params)


async def get_clan_leaguegroup(clan_tag: str) -> tuple[int, Any]:
    encoded = encode_clan_tag(clan_tag)
    return await _coc_request(f"/clans/{encoded}/currentwar/leaguegroup")


async def get_player_profile(player_tag: str) -> tuple[int, Any]:
    encoded = encode_player_tag(player_tag)
    status_code, payload = await _coc_request(f"/players/{encoded}")
    if status_code == 200 and isinstance(payload, dict):
        enriched = format_coc_player(payload)
        return 200, {
            **enriched,
            "player": enriched,
            "players": [enriched],
            "items": [enriched],
            "source": "live",
        }
    return status_code, payload


async def search_players(
    *,
    q: str | None = None,
    tag: str | None = None,
    name: str | None = None,
    clan_tag: str | None = None,
    limit: int | None = None,
) -> tuple[int, Any]:
    """Search Clash of Clans players by #TAG or name via GET /v1/players/{playerTag} and clan rosters."""
    raw_query = (tag or q or name or "").strip()
    max_results = max(1, min(int(limit or 25), 50))
    explicit_tag = bool(tag) or raw_query.startswith("#") or raw_query.upper().startswith("%23")

    # 1. Try direct player lookup against GET /v1/players/{playerTag}
    if raw_query:
        try:
            encoded_tag = encode_player_tag(raw_query)
            status_code, payload = await _coc_request(f"/players/{encoded_tag}")
            if status_code == 200 and isinstance(payload, dict) and payload.get("tag"):
                enriched = format_coc_player(payload)
                if clan_tag:
                    expected_clan = normalize_clan_tag(clan_tag)
                    if enriched.get("clan_tag") and normalize_clan_tag(enriched["clan_tag"]) != expected_clan:
                        return 200, {
                            "player": None,
                            "players": [],
                            "items": [],
                            "source": "live",
                        }
                return 200, {
                    **enriched,
                    "player": enriched,
                    "players": [enriched],
                    "items": [enriched],
                    "source": "live",
                }
            if explicit_tag and not clan_tag:
                return status_code, payload
        except ValueError:
            if explicit_tag:
                raise HTTPException(status_code=400, detail="Invalid player tag")

    # 2. If searching by player name (or within a specific clan), search clan rosters
    matched_players: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    needle = raw_query.lstrip("#").lower()

    def _collect_from_clan_payload(c_payload: dict[str, Any], default_tag: str = "") -> None:
        fallback_clan = {
            "tag": c_payload.get("tag") or default_tag,
            "name": c_payload.get("name", ""),
            "clanLevel": c_payload.get("clanLevel"),
            "badgeUrls": c_payload.get("badgeUrls", {}),
        }
        for member in c_payload.get("memberList") or []:
            m_tag_raw = str(member.get("tag", ""))
            if not m_tag_raw or m_tag_raw in seen_tags:
                continue
            m_name = str(member.get("name", "")).lower()
            m_tag = m_tag_raw.lstrip("#").lower()
            if not needle or needle in m_name or needle in m_tag:
                seen_tags.add(m_tag_raw)
                matched_players.append(format_coc_player(member, fallback_clan=fallback_clan))
                if len(matched_players) >= max_results:
                    break

    if clan_tag:
        c_status, c_payload = await get_clan_profile(clan_tag)
        if c_status == 200 and isinstance(c_payload, dict):
            _collect_from_clan_payload(c_payload, normalize_clan_tag(clan_tag))
    else:
        # Check default clan #2PP roster first so name searches find known clan members fast
        c_status, c_payload = await get_clan_profile("#2PP")
        if c_status == 200 and isinstance(c_payload, dict):
            _collect_from_clan_payload(c_payload, "#2PP")

        if len(matched_players) < max_results and len(needle) >= 3:
            c_status, c_payload = await _coc_request("/clans", params={"name": raw_query, "limit": 3})
            if c_status == 200 and isinstance(c_payload, dict):
                for clan_summary in (c_payload.get("items") or [])[:2]:
                    c_tag = clan_summary.get("tag")
                    if not c_tag:
                        continue
                    prof_status, prof_payload = await get_clan_profile(c_tag)
                    if prof_status == 200 and isinstance(prof_payload, dict):
                        _collect_from_clan_payload(prof_payload, c_tag)
                    if len(matched_players) >= max_results:
                        break

    if matched_players:
        first = matched_players[0]
        return 200, {
            **first,
            "player": first,
            "players": matched_players,
            "items": matched_players,
            "source": "live",
        }

    return 200, {
        "player": None,
        "players": [],
        "items": [],
        "source": "live",
    }

