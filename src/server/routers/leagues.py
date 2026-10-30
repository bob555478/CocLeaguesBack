from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from ..auth import verify_neon_auth_user
from ..config import normalize_clan_tag
from ..db import (
    delete_league_by_clan_tag,
    get_league_by_clan_tag,
    list_leagues,
    update_league_day,
    upsert_league,
)
from ..realtime import clan_league_live_query, seal_live_query
from ..schemas import (
    CommittedLeagueResponse,
    DeleteLeagueResponse,
    ErrorResponse,
    LeagueRow,
    ListLeaguesResponse,
    PatchDayLineupRequest,
    SaveLeagueRequest,
    SealedLiveQueryResponse,
    SealLiveQueryRequest,
)

router = APIRouter(prefix="/api/leagues")


@router.post(
    "/live",
    tags=["3. Neon Realtime & Auth / System"],
    summary="Seal Live SQL Query",
    description=(
        "Takes `{ clanTag }` in the request body, builds a deterministic parameterized query "
        "(`clanLeagueLiveQuery(clanTag)`), and seals it on the backend using `NEON_REALTIME_SECRET`. "
        "Returns a short-lived `SealedLiveQuery` capability that the React frontend passes to "
        "`useLiveQuery()` to receive live Postgres updates over WebSocket."
    ),
    response_model=SealedLiveQueryResponse,
    responses={400: {"model": ErrorResponse}},
)
async def route_seal_league_live_query(
    payload: SealLiveQueryRequest = Body(...),
):
    clan_tag = payload.clanTag or payload.clan_tag
    if not clan_tag or not str(clan_tag).strip():
        raise HTTPException(status_code=400, detail="clanTag is required")

    try:
        query = clan_league_live_query(str(clan_tag))
        sealed = seal_live_query(query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return sealed


@router.get(
    "",
    tags=["2. CWL League Organization (Lakebase Postgres)"],
    summary="List Saved League Setups",
    description=(
        "Returns saved CWL league schedules from Lakebase Postgres. Accepts an optional "
        "`?clanTag=%232PP` query parameter to filter by a specific clan."
    ),
    response_model=ListLeaguesResponse,
)
async def route_list_leagues(
    clanTag: str | None = Query(default=None, description="Optional clan tag filter (e.g. #2PP or %232PP)"),
    clan_tag: str | None = Query(default=None, include_in_schema=False),
):
    filter_tag = clanTag or clan_tag
    leagues = await list_leagues(clan_tag=filter_tag)
    return {"leagues": leagues}


@router.get(
    "/{clanTag}",
    tags=["2. CWL League Organization (Lakebase Postgres)"],
    summary="Get Clan's Saved CWL Setup",
    description=(
        "Loads a specific clan's saved 7-day schedule (`lineup_size` of 15/25/30, `opted_in_tags`, "
        "`schedule_by_day` for Days 1–7, and `opponents_by_day`)."
    ),
    responses={200: {"model": LeagueRow}, 404: {"model": ErrorResponse}},
)
async def route_get_league(
    clanTag: str = Path(..., description="Clan tag (e.g. #2PP or %232PP)", examples=["#2PP"]),
):
    try:
        league = await get_league_by_clan_tag(clanTag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not league:
        raise HTTPException(
            status_code=404,
            detail=f"No saved CWL league schedule found for clan {normalize_clan_tag(clanTag)}",
        )
    return {"league": league, **league}


@router.post(
    "",
    tags=["2. CWL League Organization (Lakebase Postgres)"],
    summary="Save / Upsert Full 7-Day CWL Schedule",
    description=(
        "Verifies the user's Neon Auth Bearer token (`verifyNeonAuthUser`), upserts the clan's "
        "complete 7-day schedule, opted-in roster, and daily lineup size (`15`, `25`, `30`) into "
        "`cwl_leagues`, and returns `{ kind: \"committed\", txid, league }`."
    ),
    response_model=CommittedLeagueResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def route_save_league(
    payload: SaveLeagueRequest = Body(...),
    user: dict[str, Any] = Depends(verify_neon_auth_user),
):
    body = payload.model_dump(exclude_none=True)

    clan_tag = payload.clanTag or payload.clan_tag or body.get("clanTag") or body.get("clan_tag")
    if not clan_tag or not str(clan_tag).strip():
        raise HTTPException(status_code=400, detail="clanTag is required")

    clan_name = payload.clanName or payload.clan_name or str(clan_tag)
    league_id = payload.id
    lineup_size = (
        payload.lineupSize
        if payload.lineupSize is not None
        else (payload.lineup_size if payload.lineup_size is not None else 15)
    )
    opted_in_tags = (
        payload.optedInTags
        if payload.optedInTags is not None
        else (payload.opted_in_tags if payload.opted_in_tags is not None else [])
    )
    schedule_by_day = (
        payload.scheduleByDay
        if payload.scheduleByDay is not None
        else (payload.schedule_by_day if payload.schedule_by_day is not None else {})
    )
    opponents_by_day = (
        payload.opponentsByDay
        if payload.opponentsByDay is not None
        else (payload.opponents_by_day if payload.opponents_by_day is not None else {})
    )

    try:
        league, txid = await upsert_league(
            clan_tag=str(clan_tag),
            clan_name=str(clan_name),
            user_id=user["id"],
            user_email=user.get("email") or payload.userEmail or payload.user_email,
            lineup_size=int(lineup_size),
            opted_in_tags=opted_in_tags,
            schedule_by_day=schedule_by_day,
            opponents_by_day=opponents_by_day,
            league_id=str(league_id) if league_id else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "kind": "committed",
        "txid": txid,
        "league": league,
    }


@router.patch(
    "/{clanTag}/day/{day}",
    tags=["2. CWL League Organization (Lakebase Postgres)"],
    summary="Update Single War Day Lineup",
    description=(
        "Updates only Day `1`–`7`'s assigned player array in Postgres using `jsonb_set` "
        "and returns `{ kind: \"committed\", txid, league }`."
    ),
    response_model=CommittedLeagueResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def route_patch_league_day(
    clanTag: str = Path(..., description="Clan tag (e.g. #2PP or %232PP)", examples=["#2PP"]),
    day: int = Path(..., ge=1, le=7, description="CWL War Day (1 to 7)", examples=[1]),
    body: PatchDayLineupRequest | list[str] = Body(
        ...,
        examples=[{"players": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"]}],
    ),
):
    if day < 1 or day > 7:
        raise HTTPException(status_code=400, detail="Day must be an integer between 1 and 7")

    player_tags: list[str] | None = None
    if isinstance(body, list):
        player_tags = [str(tag) for tag in body]
    elif isinstance(body, PatchDayLineupRequest):
        raw = body.model_dump(exclude_none=True)
        for key in ("players", "playerTags", "player_tags", "tags", "lineup", "dayLineup"):
            if key in raw and isinstance(raw[key], list):
                player_tags = [str(tag) for tag in raw[key]]
                break

    if player_tags is None:
        raise HTTPException(
            status_code=400,
            detail='Request body must contain a player tags array (e.g. { "players": ["#TAG"] })',
        )

    try:
        result = await update_league_day(clanTag, day, player_tags)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No saved CWL league schedule found for clan {normalize_clan_tag(clanTag)}",
        )

    league, txid = result
    return {
        "kind": "committed",
        "txid": txid,
        "league": league,
    }


@router.delete(
    "/{clanTag}",
    tags=["2. CWL League Organization (Lakebase Postgres)"],
    summary="Reset / Delete Saved League Setup",
    description="Removes a clan's saved schedule from Lakebase Postgres and returns its `txid`.",
    response_model=DeleteLeagueResponse,
    responses={404: {"model": ErrorResponse}},
)
async def route_delete_league(
    clanTag: str = Path(..., description="Clan tag (e.g. #2PP or %232PP)", examples=["#2PP"]),
):
    try:
        deleted = await delete_league_by_clan_tag(clanTag)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No saved CWL league schedule found for clan {normalize_clan_tag(clanTag)}",
        )

    return {
        "kind": "committed",
        "id": deleted["id"],
        "clan_tag": deleted["clan_tag"],
        "clanTag": deleted["clan_tag"],
        "txid": deleted["txid"],
    }
