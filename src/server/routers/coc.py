from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from ..coc import (
    get_clan_leaguegroup,
    get_clan_members,
    get_clan_profile,
    get_player_profile,
    search_clans,
    search_players,
)
from ..schemas import ErrorResponse

router = APIRouter(
    prefix="/api/coc",
    tags=["1. Clash of Clans (CoC) API"],
)


@router.get(
    "/clans",
    summary="Search Clans",
    description=(
        "Searches clans by `name` (min 3 chars) and filters (`warFrequency`, `minClanLevel`, "
        "`minMembers`, `maxMembers`, `minClanPoints`, `locationId`, `limit`). Attaches the server's "
        "`Authorization: Bearer <COC_API_TOKEN>` header."
    ),
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def route_search_coc_clans(
    name: str | None = Query(default=None, description="Clan name search query (minimum 3 characters)"),
    warFrequency: str | None = Query(default=None, description="Filter by clan war frequency"),
    minClanLevel: int | None = Query(default=None, description="Minimum clan level"),
    minMembers: int | None = Query(default=None, description="Minimum number of clan members"),
    maxMembers: int | None = Query(default=None, description="Maximum number of clan members"),
    minClanPoints: int | None = Query(default=None, description="Minimum clan points"),
    locationId: int | str | None = Query(default=None, description="Location ID filter"),
    limit: int | None = Query(default=None, description="Maximum number of clans to return"),
    after: str | None = Query(default=None, description="Pagination cursor (after)"),
    before: str | None = Query(default=None, description="Pagination cursor (before)"),
    labelIds: str | None = Query(default=None, description="Comma-separated label IDs"),
):
    status_code, payload = await search_clans(
        name=name,
        warFrequency=warFrequency,
        minClanLevel=minClanLevel,
        minMembers=minMembers,
        maxMembers=maxMembers,
        minClanPoints=minClanPoints,
        locationId=locationId,
        limit=limit,
        after=after,
        before=before,
        labelIds=labelIds,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get(
    "/clans/{clanTag}/currentwar/leaguegroup",
    summary="Get Active CWL Group & Rounds",
    description=(
        "Fetches the active 7-day Clan War League group, the 6 opponent clans in your group, "
        "and the war tags for each of the 7 CWL rounds."
    ),
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def route_get_coc_clan_leaguegroup(
    clanTag: str = Path(..., description="Clan tag (e.g. #2PP or %232PP)", examples=["#2PP"]),
):
    status_code, payload = await get_clan_leaguegroup(clanTag)
    return JSONResponse(status_code=status_code, content=payload)


@router.get(
    "/clans/{clanTag}/members",
    summary="Get Clan Members List",
    description=(
        "Fetches only the clan's current member roster for refreshing player opt-in status "
        "or Town Hall levels without pulling full clan metadata."
    ),
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def route_get_coc_clan_members(
    clanTag: str = Path(..., description="Clan tag (e.g. #2PP or %232PP)", examples=["#2PP"]),
    limit: int | None = Query(default=None, description="Maximum number of members to return"),
    after: str | None = Query(default=None, description="Pagination cursor (after)"),
    before: str | None = Query(default=None, description="Pagination cursor (before)"),
):
    status_code, payload = await get_clan_members(
        clanTag, limit=limit, after=after, before=before
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get(
    "/clans/{clanTag}",
    summary="Get Clan Profile & Full Roster",
    description=(
        "URL-encodes the `#TAG` (`%23TAG`) and fetches a clan's full metadata, war league, "
        "and `memberList` (Town Hall levels, roles, trophies, war preferences) used to populate "
        "the CWL League Setup page."
    ),
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def route_get_coc_clan_profile(
    clanTag: str = Path(..., description="Clan tag (e.g. #2PP or %232PP)", examples=["#2PP"]),
):
    status_code, payload = await get_clan_profile(clanTag)
    return JSONResponse(status_code=status_code, content=payload)


@router.get(
    "/players",
    summary="Search In-Game Players",
    description=(
        "Searches Clash of Clans players by name or `#TAG` (used during Registration and Account "
        "Management to link an online user to their in-game player(s) and detect their clan)."
    ),
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def route_search_coc_players(
    q: str | None = Query(default=None, description="Search query (player #TAG or player name)"),
    tag: str | None = Query(default=None, description="Player tag (e.g. #P902L8Q or %23P902L8Q)"),
    playerTag: str | None = Query(default=None, description="Alias for player tag"),
    player_tag: str | None = Query(default=None, include_in_schema=False),
    name: str | None = Query(default=None, description="Player name search query"),
    query: str | None = Query(default=None, include_in_schema=False),
    clanTag: str | None = Query(default=None, description="Optional clan tag to scope player search"),
    clan_tag: str | None = Query(default=None, include_in_schema=False),
    limit: int | None = Query(default=None, description="Maximum number of players to return"),
):
    resolved_tag = tag or playerTag or player_tag
    resolved_query = q or query
    resolved_clan_tag = clanTag or clan_tag
    status_code, payload = await search_players(
        q=resolved_query,
        tag=resolved_tag,
        name=name,
        clan_tag=resolved_clan_tag,
        limit=limit,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get(
    "/players/{playerTag}",
    summary="Get In-Game Player by Tag",
    description="Fetches a Clash of Clans player profile by `#TAG` (`GET /v1/players/{playerTag}`).",
    include_in_schema=False,
)
async def route_get_coc_player_by_tag(
    playerTag: str = Path(..., description="Player tag (e.g. #P902L8Q or %23P902L8Q)"),
):
    status_code, payload = await get_player_profile(playerTag)
    return JSONResponse(status_code=status_code, content=payload)
