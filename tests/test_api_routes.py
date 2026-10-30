import base64
import json
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx
import jwt
import pytest

from src.server.api import app
from src.server.config import get_neon_auth_base_url, get_neon_realtime_secret
from src.server.db import get_async_connection
from src.server.realtime import (
    _decode_base64url,
    clan_league_live_query,
    compute_query_fingerprint,
    parse_realtime_secret,
)


def _generate_test_eddsa_jwk_and_token(user_id: str = "test-user-123", email: str = "leader@coc.example"):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes_raw()
    x_b64 = base64.urlsafe_b64encode(pub_bytes).decode("ascii").rstrip("=")
    kid = "test-ed25519-key"
    jwk_dict = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": x_b64,
        "kid": kid,
        "alg": "EdDSA",
        "use": "sig",
    }
    now = int(time.time())
    base_url = get_neon_auth_base_url() or "https://example.neon.tech/neondb/auth"
    payload = {
        "sub": user_id,
        "email": email,
        "name": "Test Clan Leader",
        "iat": now,
        "exp": now + 900,
        "iss": base_url,
    }
    token = jwt.encode(payload, private_key, algorithm="EdDSA", headers={"kid": kid})
    return {"keys": [jwk_dict]}, token


@pytest.mark.asyncio
async def test_neon_status_and_live_query_sealing():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Check /api/neon/status against live Lakebase Postgres, Neon Auth JWKS, and Neon Realtime
        res = await client.get("/api/neon/status")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["postgres"]["connected"] is True
        assert data["postgres"]["database"] == "neondb"
        assert data["auth"]["jwksReachable"] is True
        assert data["realtime"]["sealed"] is True

        # 2. Check POST /api/leagues/live
        live_res = await client.post("/api/leagues/live", json={"clanTag": "#2PP"})
        assert live_res.status_code == 200
        sealed = live_res.json()
        assert "capability" in sealed
        assert "queryFingerprint" in sealed
        assert "expiresAt" in sealed

        # Verify Compact JWE structure and decrypt with NEON_REALTIME_SECRET
        parts = sealed["capability"].split(".")
        assert len(parts) == 5
        encoded_header, encrypted_key, encoded_iv, encoded_ciphertext, encoded_tag = parts
        assert encrypted_key == ""

        key = parse_realtime_secret(get_neon_realtime_secret())
        iv = _decode_base64url(encoded_iv)
        ciphertext = _decode_base64url(encoded_ciphertext)
        tag = _decode_base64url(encoded_tag)

        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(iv, ciphertext + tag, encoded_header.encode("utf-8"))
        claims = json.loads(decrypted.decode("utf-8"))

        expected_query = clan_league_live_query("#2PP")
        assert claims["v"] == 1
        assert claims["aud"] == "realtime-proxy"
        assert claims["database"] == "neondb"
        assert claims["query_fingerprint"] == compute_query_fingerprint(expected_query)
        assert claims["query_fingerprint"] == sealed["queryFingerprint"]
        assert claims["sql"] == expected_query.sql
        assert len(claims["parameters"]) == 1


@pytest.mark.asyncio
async def test_leagues_crud_lifecycle(monkeypatch):
    jwks_data, token = _generate_test_eddsa_jwk_and_token()

    async def mock_fetch_jwks(jwks_url=None, force_refresh=False):
        return jwks_data

    monkeypatch.setattr("src.server.auth.fetch_jwks", mock_fetch_jwks)

    test_tag = "#99TESTCWL"
    encoded_test_tag = "%2399TESTCWL"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Ensure existing #2PP league is returned by GET /api/leagues
        list_res = await client.get("/api/leagues?clanTag=%232PP")
        assert list_res.status_code == 200
        leagues = list_res.json()["leagues"]
        assert any(l["clan_tag"] == "#2PP" for l in leagues)

        # 2. Verify POST /api/leagues requires Neon Auth Bearer token
        unauth_res = await client.post("/api/leagues", json={"clanTag": test_tag})
        assert unauth_res.status_code == 401

        # 3. Upsert full 7-day CWL schedule with POST /api/leagues
        schedule = {str(day): ["#P1", "#P2", "#P3"] for day in range(1, 8)}
        opponents = {str(day): f"Opponent {day}" for day in range(1, 8)}
        save_res = await client.post(
            "/api/leagues",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "clanTag": test_tag,
                "clanName": "PyTest CWL Clan",
                "lineupSize": 15,
                "optedInTags": ["#P1", "#P2", "#P3", "#P4"],
                "scheduleByDay": schedule,
                "opponentsByDay": opponents,
            },
        )
        assert save_res.status_code == 200
        save_data = save_res.json()
        assert save_data["kind"] == "committed"
        assert save_data["txid"].isdigit()
        assert save_data["league"]["clan_tag"] == test_tag
        assert save_data["league"]["clan_name"] == "PyTest CWL Clan"
        assert save_data["league"]["lineup_size"] == 15

        # 4. Get single clan's saved setup via GET /api/leagues/:clanTag
        get_res = await client.get(f"/api/leagues/{encoded_test_tag}")
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["league"]["clan_tag"] == test_tag
        assert get_data["schedule_by_day"]["3"] == ["#P1", "#P2", "#P3"]

        # 5. Update single war day lineup via PATCH /api/leagues/:clanTag/day/:day
        patch_res = await client.patch(
            f"/api/leagues/{encoded_test_tag}/day/3",
            json={"players": ["#P1", "#P4"]},
        )
        assert patch_res.status_code == 200
        patch_data = patch_res.json()
        assert patch_data["kind"] == "committed"
        assert patch_data["txid"].isdigit()
        assert patch_data["league"]["schedule_by_day"]["3"] == ["#P1", "#P4"]
        assert patch_data["league"]["schedule_by_day"]["1"] == ["#P1", "#P2", "#P3"]

        # 6. Delete the test setup via DELETE /api/leagues/:clanTag
        del_res = await client.delete(f"/api/leagues/{encoded_test_tag}")
        assert del_res.status_code == 200
        del_data = del_res.json()
        assert del_data["kind"] == "committed"
        assert del_data["id"] == test_tag
        assert del_data["txid"].isdigit()

        # Confirm deletion
        after_del_res = await client.get(f"/api/leagues/{encoded_test_tag}")
        assert after_del_res.status_code == 404


@pytest.mark.asyncio
async def test_coc_upstream_routes(monkeypatch):
    captured_requests: list[tuple[str, dict, dict]] = []

    async def fake_coc_request(path: str, params=None):
        captured_requests.append((path, params or {}, {"auth": "Bearer test-coc-jwt"}))
        if path == "/clans":
            return 200, {"items": [{"tag": "#2PP", "name": "The Order"}]}
        if path == "/clans/%232PP":
            return 200, {
                "tag": "#2PP",
                "name": "The Order",
                "memberList": [
                    {
                        "tag": "#P902L8Q",
                        "name": "BarbarianKing",
                        "townHallLevel": 16,
                        "trophies": 5400,
                        "role": "leader",
                    }
                ],
            }
        if path == "/clans/%232PP/members":
            return 200, {"items": [{"tag": "#P902L8Q", "name": "BarbarianKing", "townHallLevel": 16}]}
        if path == "/clans/%232PP/currentwar/leaguegroup":
            return 200, {"state": "inWar", "season": "2026-10", "clans": [], "rounds": []}
        if path == "/players/%23P902L8Q":
            return 200, {
                "tag": "#P902L8Q",
                "name": "BarbarianKing",
                "townHallLevel": 16,
                "trophies": 5400,
                "role": "leader",
                "clan": {
                    "tag": "#2PP",
                    "name": "The Order",
                    "badgeUrls": {"medium": "https://example.com/badge.png"},
                },
            }
        return 404, {"reason": "notFound"}

    monkeypatch.setattr("src.server.coc._coc_request", fake_coc_request)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Validation: name < 3 chars returns 400
        bad_search = await client.get("/api/coc/clans?name=ab")
        assert bad_search.status_code == 400

        # 1. GET /api/coc/clans
        res1 = await client.get("/api/coc/clans?name=Order&minClanLevel=10&limit=5")
        assert res1.status_code == 200
        assert res1.json()["items"][0]["tag"] == "#2PP"
        assert captured_requests[-1][0] == "/clans"
        assert captured_requests[-1][1]["name"] == "Order"
        assert captured_requests[-1][1]["minClanLevel"] == 10
        assert captured_requests[-1][1]["limit"] == 5

        # 2. GET /api/coc/clans/:clanTag
        res2 = await client.get("/api/coc/clans/%232PP")
        assert res2.status_code == 200
        assert res2.json()["tag"] == "#2PP"
        assert captured_requests[-1][0] == "/clans/%232PP"

        # 3. GET /api/coc/clans/:clanTag/members
        res3 = await client.get("/api/coc/clans/%232PP/members")
        assert res3.status_code == 200
        assert res3.json()["items"][0]["tag"] == "#P902L8Q"
        assert captured_requests[-1][0] == "/clans/%232PP/members"

        # 4. GET /api/coc/clans/:clanTag/currentwar/leaguegroup
        res4 = await client.get("/api/coc/clans/%232PP/currentwar/leaguegroup")
        assert res4.status_code == 200
        assert res4.json()["state"] == "inWar"
        assert captured_requests[-1][0] == "/clans/%232PP/currentwar/leaguegroup"

        # 5. GET /api/coc/players (by #TAG and by name)
        res5 = await client.get("/api/coc/players?tag=%23P902L8Q")
        assert res5.status_code == 200
        p_data = res5.json()
        assert p_data["tag"] == "#P902L8Q"
        assert p_data["player_tag"] == "#P902L8Q"
        assert p_data["clan_tag"] == "#2PP"
        assert p_data["source"] == "live"
        assert p_data["items"][0]["name"] == "BarbarianKing"
        assert p_data["players"][0]["player_name"] == "BarbarianKing"
        assert captured_requests[-1][0] == "/players/%23P902L8Q"

        res6 = await client.get("/api/coc/players?q=Barbarian&clanTag=%232PP")
        assert res6.status_code == 200
        assert res6.json()["source"] == "live"
        assert res6.json()["items"][0]["tag"] == "#P902L8Q"
        assert res6.json()["players"][0]["tag"] == "#P902L8Q"


@pytest.mark.asyncio
async def test_user_ingame_accounts_lifecycle(monkeypatch):
    test_user_id = "pytest-user-accounts-999"
    jwks_data, token = _generate_test_eddsa_jwk_and_token(user_id=test_user_id)

    async def mock_fetch_jwks(jwks_url=None, force_refresh=False):
        return jwks_data

    monkeypatch.setattr("src.server.auth.fetch_jwks", mock_fetch_jwks)
    headers = {"Authorization": f"Bearer {token}"}

    # Clean up any leftover test rows before running
    async with await get_async_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM public.user_ingame_accounts WHERE user_id = %s",
                (test_user_id,),
            )

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Unauthenticated request returns 401
            unauth = await client.get("/api/accounts")
            assert unauth.status_code == 401

            # 2. Link first in-game account via POST /api/accounts -> automatically sets is_active = true
            post1 = await client.post(
                "/api/accounts",
                headers=headers,
                json={
                    "playerTag": "#P1001",
                    "playerName": "ArcherQueen",
                    "townHallLevel": 16,
                    "trophies": 5100,
                    "role": "leader",
                    "clanTag": "#2PP",
                    "clanName": "The Order",
                },
            )
            assert post1.status_code == 200
            data1 = post1.json()
            assert data1["kind"] == "committed"
            assert data1["txid"].isdigit()
            assert len(data1["accounts"]) == 1
            assert data1["accounts"][0]["player_tag"] == "#P1001"
            assert data1["accounts"][0]["is_active"] is True

            # 3. Link second in-game account via POST /api/accounts
            post2 = await client.post(
                "/api/accounts",
                headers=headers,
                json={
                    "playerTag": "#P1002",
                    "playerName": "GrandWarden",
                    "townHallLevel": 15,
                    "clanTag": "#2PP",
                    "clanName": "The Order",
                },
            )
            assert post2.status_code == 200
            data2 = post2.json()
            assert len(data2["accounts"]) == 2
            active_tags = [a["player_tag"] for a in data2["accounts"] if a["is_active"]]
            assert active_tags == ["#P1001"]

            # 4. List accounts via GET /api/accounts (both Bearer JWT and ?userId= fallback)
            list_res = await client.get("/api/accounts", headers=headers)
            assert list_res.status_code == 200
            list_data = list_res.json()
            assert len(list_data["items"]) == 2
            assert len(list_data["accounts"]) == 2
            assert list_data["activeAccount"]["player_tag"] == "#P1001"

            fallback_list = await client.get(f"/api/accounts?userId={test_user_id}")
            assert fallback_list.status_code == 200
            assert len(fallback_list.json()["items"]) == 2

            # 5. Switch active in-game player via PATCH /api/accounts/:playerTag/activate
            act_res = await client.patch(
                "/api/accounts/%23P1002/activate",
                json={"userId": test_user_id},
            )
            assert act_res.status_code == 200
            act_data = act_res.json()
            assert len(act_data["items"]) == 2
            assert act_data["activeAccount"]["player_tag"] == "#P1002"
            assert act_data["activeAccount"]["is_active"] is True
            p1_row = next(a for a in act_data["accounts"] if a["player_tag"] == "#P1001")
            assert p1_row["is_active"] is False

            # 6. Update player's clan via PATCH /api/accounts/:playerTag/clan
            clan_res = await client.patch(
                "/api/accounts/%23P1002/clan",
                headers=headers,
                json={"clanTag": "#99NEW", "clanName": "New Horizons"},
            )
            assert clan_res.status_code == 200
            clan_data = clan_res.json()
            assert clan_data["account"]["clan_tag"] == "#99NEW"
            assert clan_data["account"]["clan_name"] == "New Horizons"
            assert len(clan_data["items"]) == 2

            # 6b. Update player's clan role via PATCH /api/accounts/:playerTag/role
            role_res = await client.patch(
                "/api/accounts/%23P1002/role",
                json={"userId": test_user_id, "role": "coLeader"},
            )
            assert role_res.status_code == 200
            role_data = role_res.json()
            assert role_data["account"]["role"] == "coLeader"
            assert len(role_data["items"]) == 2

            # 7. Delete active account (#P1002) via DELETE /api/accounts/:playerTag -> promotes #P1001 to active
            del_res = await client.delete(
                "/api/accounts/%23P1002",
                headers=headers,
            )
            assert del_res.status_code == 200
            del_data = del_res.json()
            assert del_data["player_tag"] == "#P1002"
            assert len(del_data["items"]) == 1
            assert len(del_data["accounts"]) == 1
            assert del_data["accounts"][0]["player_tag"] == "#P1001"
            assert del_data["accounts"][0]["is_active"] is True

            # 8. Attempting to delete the last remaining account (total <= 1) returns HTTP 400
            del_last = await client.delete(
                "/api/accounts/%23P1001",
                headers=headers,
            )
            assert del_last.status_code == 400
            assert (
                del_last.json()["error"]
                == "Cannot remove your last in-game account. Every user must have at least 1 linked in-game player."
            )
    finally:
        async with await get_async_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM public.user_ingame_accounts WHERE user_id = %s",
                    (test_user_id,),
                )


@pytest.mark.asyncio
async def test_swagger_and_openapi_docs():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        docs_res = await client.get("/docs")
        assert docs_res.status_code == 200
        assert "SwaggerUIBundle" in docs_res.text

        swagger_res = await client.get("/swagger")
        assert swagger_res.status_code == 200
        assert "SwaggerUIBundle" in swagger_res.text

        redoc_res = await client.get("/redoc")
        assert redoc_res.status_code == 200

        openapi_res = await client.get("/openapi.json")
        assert openapi_res.status_code == 200
        schema = openapi_res.json()
        assert schema["info"]["title"] == "CoC Leagues Backend API"
        assert "NeonAuthBearer" in schema["components"]["securitySchemes"]
        expected_paths = {
            "/api/coc/clans",
            "/api/coc/clans/{clanTag}",
            "/api/coc/clans/{clanTag}/members",
            "/api/coc/clans/{clanTag}/currentwar/leaguegroup",
            "/api/coc/players",
            "/api/leagues",
            "/api/leagues/{clanTag}",
            "/api/leagues/{clanTag}/day/{day}",
            "/api/leagues/live",
            "/api/neon/status",
            "/api/accounts",
            "/api/accounts/{playerTag}",
            "/api/accounts/{playerTag}/activate",
            "/api/accounts/{playerTag}/clan",
            "/api/accounts/{playerTag}/role",
        }
        assert expected_paths.issubset(set(schema["paths"].keys()))

