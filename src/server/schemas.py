from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Human-readable error message")
    detail: Any = Field(..., description="Detailed error description")


class LeagueRow(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "#2PP",
                "clan_tag": "#2PP",
                "clan_name": "The Order",
                "user_id": "0ad13ad2-a8c7-48c2-8a1d-a112f283c2bf",
                "user_email": "leader@example.com",
                "lineup_size": 15,
                "opted_in_tags": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                "schedule_by_day": {
                    "1": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "2": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "3": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "4": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "5": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "6": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "7": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                },
                "opponents_by_day": {
                    "1": "Tribe Gaming",
                    "2": "Israel Elite",
                    "3": "Apex Legends CoC",
                    "4": "Royal Knights",
                    "5": "Nightfall Academy",
                    "6": "Opponent Clan #6",
                    "7": "Final Round Clan",
                },
                "updated_at": "2026-10-30T12:32:46.906Z",
            }
        }
    )

    id: str = Field(..., description="Primary key (normalized clan tag, e.g. #2PP)")
    clan_tag: str = Field(..., description="Normalized Clash of Clans clan tag (#TAG)")
    clan_name: str = Field(..., description="Clan display name")
    user_id: str = Field(..., description="Neon Auth user ID who saved the schedule")
    user_email: str | None = Field(default=None, description="Neon Auth user email")
    lineup_size: int = Field(default=15, description="Daily war lineup size (15, 25, or 30)")
    opted_in_tags: list[str] = Field(default_factory=list, description="Opted-in player tags")
    schedule_by_day: dict[str, list[str]] = Field(
        default_factory=dict,
        description="7-day schedule mapping day ('1'..'7') to assigned player tags",
    )
    opponents_by_day: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of war day ('1'..'7') to opponent clan name",
    )
    updated_at: str = Field(..., description="ISO-8601 UTC timestamp of last update")


class ListLeaguesResponse(BaseModel):
    leagues: list[LeagueRow]


class SaveLeagueRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
        json_schema_extra={
            "example": {
                "clanTag": "#2PP",
                "clanName": "The Order",
                "lineupSize": 15,
                "optedInTags": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                "scheduleByDay": {
                    "1": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "2": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "3": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "4": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "5": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "6": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                    "7": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
                },
                "opponentsByDay": {
                    "1": "Tribe Gaming",
                    "2": "Israel Elite",
                    "3": "Apex Legends CoC",
                    "4": "Royal Knights",
                    "5": "Nightfall Academy",
                    "6": "Opponent Clan #6",
                    "7": "Final Round Clan",
                },
            }
        },
    )

    id: str | None = Field(default=None, description="Optional row ID (defaults to normalized clanTag)")
    clanTag: str | None = Field(default=None, description="Clan tag (e.g. #2PP)")
    clan_tag: str | None = Field(default=None, description="Snake-case alias for clanTag")
    clanName: str | None = Field(default=None, description="Clan name (e.g. The Order)")
    clan_name: str | None = Field(default=None, description="Snake-case alias for clanName")
    lineupSize: int | None = Field(default=None, description="Daily war lineup size (15, 25, or 30)")
    lineup_size: int | None = Field(default=None, description="Snake-case alias for lineupSize")
    optedInTags: list[str] | None = Field(default=None, description="Array of opted-in player tags")
    opted_in_tags: list[str] | None = Field(default=None, description="Snake-case alias for optedInTags")
    scheduleByDay: dict[str, list[str]] | None = Field(
        default=None, description="7-day lineup schedule ('1'..'7')"
    )
    schedule_by_day: dict[str, list[str]] | None = Field(
        default=None, description="Snake-case alias for scheduleByDay"
    )
    opponentsByDay: dict[str, str] | None = Field(
        default=None, description="7-day opponent names ('1'..'7')"
    )
    opponents_by_day: dict[str, str] | None = Field(
        default=None, description="Snake-case alias for opponentsByDay"
    )
    userEmail: str | None = Field(default=None, description="Optional user email override")
    user_email: str | None = Field(default=None, description="Snake-case alias for userEmail")


class CommittedLeagueResponse(BaseModel):
    kind: Literal["committed"] = "committed"
    txid: str = Field(..., description="Postgres transaction ID (pg_current_xact_id()::text) for Neon Realtime awaitTxId()")
    league: LeagueRow


class PatchDayLineupRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "players": ["#P902L8Q", "#28YJ99R", "#88GLP2Q"],
            }
        },
    )

    players: list[str] | None = Field(
        default=None, description="Assigned player tags for the war day"
    )
    playerTags: list[str] | None = Field(
        default=None, description="Alias for players"
    )
    player_tags: list[str] | None = Field(
        default=None, description="Alias for players"
    )
    tags: list[str] | None = Field(
        default=None, description="Alias for players"
    )
    lineup: list[str] | None = Field(
        default=None, description="Alias for players"
    )
    dayLineup: list[str] | None = Field(
        default=None, description="Alias for players"
    )


class DeleteLeagueResponse(BaseModel):
    kind: Literal["committed"] = "committed"
    id: str = Field(..., description="Deleted league row ID")
    clan_tag: str = Field(..., description="Deleted clan tag")
    clanTag: str = Field(..., description="Deleted clan tag (camelCase)")
    txid: str = Field(..., description="Postgres transaction ID (pg_current_xact_id()::text)")


class SealLiveQueryRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"example": {"clanTag": "#2PP"}},
    )

    clanTag: str | None = Field(default=None, description="Clan tag to subscribe to (e.g. #2PP)")
    clan_tag: str | None = Field(default=None, description="Snake-case alias for clanTag")


class SealedLiveQueryResponse(BaseModel):
    capability: str = Field(..., description="Encrypted Compact-JWE capability token for Neon Realtime")
    queryFingerprint: str = Field(..., description="SHA-256 fingerprint of the canonical query and parameters")
    expiresAt: int = Field(..., description="Expiration timestamp in Unix milliseconds")


class NeonStatusResponse(BaseModel):
    ok: bool = Field(..., description="True when Postgres, Neon Auth JWKS, and Neon Realtime sealing are all operational")
    postgres: dict[str, Any] = Field(..., description="Lakebase Postgres connection health")
    auth: dict[str, Any] = Field(..., description="Neon Auth JWKS status and caller token verification")
    realtime: dict[str, Any] = Field(..., description="Neon Realtime query sealing verification")


class InGameAccountRow(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "id": "0ad13ad2-a8c7-48c2-8a1d-a112f283c2bf:#P902L8Q",
                "user_id": "0ad13ad2-a8c7-48c2-8a1d-a112f283c2bf",
                "player_tag": "#P902L8Q",
                "player_name": "BarbarianKing",
                "town_hall_level": 16,
                "trophies": 5400,
                "role": "leader",
                "clan_tag": "#2PP",
                "clan_name": "The Order",
                "clan_badge_url": "https://api-assets.clashofclans.com/badges/200/badge.png",
                "is_active": True,
                "created_at": "2026-10-30T14:00:00.000Z",
                "updated_at": "2026-10-30T14:00:00.000Z",
            }
        },
    )

    id: str = Field(..., description="Primary key (`<user_id>:<player_tag>`)")
    user_id: str = Field(..., description="Online Neon Auth user ID")
    player_tag: str = Field(..., description="Normalized Clash of Clans player tag (#TAG)")
    player_name: str = Field(..., description="In-game player display name")
    town_hall_level: int = Field(default=16, description="Player Town Hall level")
    trophies: int = Field(default=0, description="Player trophy count")
    role: str | None = Field(default="member", description="Clan role (member, admin, coLeader, leader)")
    clan_tag: str = Field(..., description="Normalized Clash of Clans clan tag (#TAG)")
    clan_name: str = Field(..., description="Assigned clan display name")
    clan_badge_url: str | None = Field(default=None, description="Optional clan badge image URL")
    is_active: bool = Field(default=False, description="Whether this is the user's currently active in-game character")
    created_at: str | None = Field(default=None, description="ISO-8601 UTC creation timestamp")
    updated_at: str | None = Field(default=None, description="ISO-8601 UTC last update timestamp")


class ListAccountsResponse(BaseModel):
    items: list[InGameAccountRow]
    accounts: list[InGameAccountRow]
    activeAccount: InGameAccountRow | None = None


class LinkAccountItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    playerTag: str | None = Field(default=None, description="Player tag (e.g. #P902L8Q)")
    player_tag: str | None = None
    tag: str | None = None
    playerName: str | None = Field(default=None, description="Player name (e.g. BarbarianKing)")
    player_name: str | None = None
    name: str | None = None
    townHallLevel: int | None = Field(default=None, description="Town Hall level (e.g. 16)")
    town_hall_level: int | None = None
    trophies: int | None = Field(default=None, description="Current trophies")
    role: str | None = Field(default=None, description="Clan role")
    clanTag: str | None = Field(default=None, description="Assigned clan tag (e.g. #2PP)")
    clan_tag: str | None = None
    clanName: str | None = Field(default=None, description="Assigned clan name (e.g. The Order)")
    clan_name: str | None = None
    clanBadgeUrl: str | None = None
    clan_badge_url: str | None = None
    isActive: bool | None = None
    is_active: bool | None = None


class LinkAccountsRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "userId": "user_123",
                "accounts": [
                    {
                        "playerTag": "#P902L8Q",
                        "playerName": "Artorius",
                        "townHallLevel": 17,
                        "trophies": 5890,
                        "role": "leader",
                        "clanTag": "#2PP",
                        "clanName": "The Order",
                        "isActive": True,
                    }
                ],
            }
        },
    )

    userId: str | None = Field(default=None, description="Optional user ID fallback when not using Bearer JWT")
    user_id: str | None = None
    accounts: list[LinkAccountItem] | None = Field(
        default=None, description="Optional batch of in-game accounts to link"
    )
    players: list[LinkAccountItem] | None = Field(
        default=None, description="Alias for accounts batch"
    )
    playerTag: str | None = Field(default=None, description="Player tag when linking a single account")
    player_tag: str | None = None
    tag: str | None = None
    playerName: str | None = Field(default=None, description="Player name when linking a single account")
    player_name: str | None = None
    name: str | None = None
    townHallLevel: int | None = Field(default=None, description="Town Hall level")
    town_hall_level: int | None = None
    trophies: int | None = None
    role: str | None = None
    clanTag: str | None = Field(default=None, description="Clan tag (#TAG)")
    clan_tag: str | None = None
    clanName: str | None = Field(default=None, description="Clan display name")
    clan_name: str | None = None
    clanBadgeUrl: str | None = None
    clan_badge_url: str | None = None
    isActive: bool | None = None
    is_active: bool | None = None


class ActivateAccountRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"example": {"userId": "user_123"}},
    )

    userId: str | None = Field(default=None, description="Optional user ID fallback")
    user_id: str | None = None


class UpdateAccountClanRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "userId": "user_123",
                "clanTag": "#2Q89J0L2",
                "clanName": "Apex Legends CoC",
            }
        },
    )

    userId: str | None = Field(default=None, description="Optional user ID fallback")
    user_id: str | None = None
    clanTag: str | None = Field(default=None, description="New clan tag (#TAG)")
    clan_tag: str | None = Field(default=None, description="Snake-case alias for clanTag")
    clanName: str | None = Field(default=None, description="New clan display name")
    clan_name: str | None = Field(default=None, description="Snake-case alias for clanName")
    clanBadgeUrl: str | None = Field(default=None, description="Optional clan badge image URL")
    clan_badge_url: str | None = Field(default=None, description="Snake-case alias for clanBadgeUrl")


class UpdateAccountRoleRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "userId": "user_123",
                "role": "leader",
            }
        },
    )

    userId: str | None = Field(default=None, description="Optional user ID fallback")
    user_id: str | None = None
    role: str | None = Field(
        default=None,
        description='In-game clan role ("member", "admin", "coLeader", "leader")',
    )


class CommittedAccountsResponse(BaseModel):
    kind: Literal["committed"] = "committed"
    txid: str = Field(..., description="Postgres transaction ID (pg_current_xact_id()::text)")
    account: InGameAccountRow | None = None
    items: list[InGameAccountRow]
    accounts: list[InGameAccountRow]
    activeAccount: InGameAccountRow | None = None


class DeleteAccountResponse(BaseModel):
    kind: Literal["committed"] = "committed"
    id: str = Field(..., description="Deleted account row ID")
    player_tag: str = Field(..., description="Deleted player tag")
    playerTag: str = Field(..., description="Deleted player tag (camelCase)")
    txid: str = Field(..., description="Postgres transaction ID (pg_current_xact_id()::text)")
    items: list[InGameAccountRow]
    accounts: list[InGameAccountRow]
    activeAccount: InGameAccountRow | None = None


