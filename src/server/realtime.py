import base64
from dataclasses import dataclass
import hashlib
import json
import os
import time
from typing import Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_database_name, get_neon_realtime_secret, normalize_clan_tag

SECRET_PREFIX = "nrt_live_1"
KEY_BYTES = 32
SEALED_QUERY_LIFETIME_SECONDS = 60
IV_BYTES = 12
TAG_BYTES = 16
MAX_TOKEN_BYTES = 262144
FINGERPRINT_DOMAIN = b"neon-live-query-fingerprint-v1\x00"


@dataclass(frozen=True)
class PreparedParameter:
    typeOid: int
    value: str | None


@dataclass(frozen=True)
class PreparedLiveQuery:
    sql: str
    parameters: tuple[PreparedParameter, ...]


def _encode_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _encode_base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def parse_realtime_secret(secret: str | None = None) -> bytes:
    """Decode and validate the `nrt_live_1...` Neon Realtime secret."""
    raw_secret = secret or get_neon_realtime_secret()
    if not raw_secret or not raw_secret.startswith(SECRET_PREFIX):
        raise ValueError("Invalid Realtime secret")
    encoded_key = raw_secret[len(SECRET_PREFIX) :]
    if not encoded_key or not all(
        c.isalnum() or c in "-_" for c in encoded_key
    ):
        raise ValueError("Invalid Realtime secret")
    try:
        key = _decode_base64url(encoded_key)
    except Exception as exc:
        raise ValueError("Invalid Realtime secret") from exc
    if len(key) != KEY_BYTES or _encode_base64url(key) != encoded_key:
        raise ValueError("Invalid Realtime secret")
    return key


def raw_sql(sql: str, parameters: list[Any] | None = None) -> PreparedLiveQuery:
    """Create a prepared live SQL query matching `@neon/realtime/server` rawSql()."""
    encoded_params: list[PreparedParameter] = []
    for param in parameters or []:
        if isinstance(param, PreparedParameter):
            encoded_params.append(param)
        elif param is None:
            encoded_params.append(PreparedParameter(typeOid=0, value=None))
        elif isinstance(param, bool):
            encoded_params.append(
                PreparedParameter(typeOid=0, value="true" if param else "false")
            )
        elif isinstance(param, (str, int, float)):
            encoded_params.append(PreparedParameter(typeOid=0, value=str(param)))
        else:
            raise ValueError(f"Unsupported Realtime raw SQL parameter: {type(param)!r}")
    return PreparedLiveQuery(sql=sql, parameters=tuple(encoded_params))


def clan_league_live_query(clan_tag: str) -> PreparedLiveQuery:
    """Build the deterministic parameterized live query for a clan's CWL setup."""
    normalized_tag = normalize_clan_tag(clan_tag)
    sql = (
        "SELECT id, clan_tag, clan_name, user_id, user_email, lineup_size, "
        "opted_in_tags, schedule_by_day, opponents_by_day, updated_at "
        "FROM cwl_leagues WHERE clan_tag = $1"
    )
    return raw_sql(sql, [normalized_tag])


# Alias matching the camelCase name referenced in API_ROUTES.md
clanLeagueLiveQuery = clan_league_live_query


def compute_query_fingerprint(query: PreparedLiveQuery) -> str:
    """Compute the SHA-256 query fingerprint matching `@neon/realtime/server`."""
    canonical = {
        "sql": query.sql,
        "parameters": [
            {
                "type_oid": p.typeOid,
                "value": None if p.value is None else _encode_base64(p.value.encode("utf-8")),
            }
            for p in query.parameters
        ],
    }
    canonical_bytes = json.dumps(
        canonical, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(FINGERPRINT_DOMAIN + canonical_bytes).hexdigest()


def seal_live_query(
    query: PreparedLiveQuery,
    *,
    secret: str | None = None,
    database: str | None = None,
    debug_mode: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Seal a live query into a Compact-JWE SealedLiveQuery capability."""
    key = parse_realtime_secret(secret)
    db_name = database or get_database_name()
    db_bytes = db_name.encode("utf-8")
    if len(db_bytes) == 0 or len(db_bytes) > 63 or "\x00" in db_name:
        raise ValueError("Invalid Realtime database name")

    fingerprint = compute_query_fingerprint(query)
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    issued_at = current_ms // 1000
    expires_at = issued_at + SEALED_QUERY_LIFETIME_SECONDS

    claims = {
        "v": 1,
        "aud": "realtime-proxy",
        "database": db_name,
        "error_details": "full" if debug_mode else "safe",
        "query_fingerprint": fingerprint,
        "sql": query.sql,
        "parameters": [
            {
                "type_oid": p.typeOid,
                "value": None if p.value is None else _encode_base64(p.value.encode("utf-8")),
            }
            for p in query.parameters
        ],
        "iat": issued_at,
        "exp": expires_at,
    }

    header = {"alg": "dir", "enc": "A256GCM", "v": 1}
    encoded_header = _encode_base64url(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    iv = os.urandom(IV_BYTES)
    plaintext = json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    aad = encoded_header.encode("utf-8")

    aesgcm = AESGCM(key)
    encrypted = aesgcm.encrypt(iv, plaintext, aad)
    ciphertext = encrypted[:-TAG_BYTES]
    tag = encrypted[-TAG_BYTES:]

    capability = ".".join(
        [
            encoded_header,
            "",
            _encode_base64url(iv),
            _encode_base64url(ciphertext),
            _encode_base64url(tag),
        ]
    )
    if len(capability.encode("utf-8")) > MAX_TOKEN_BYTES:
        raise ValueError("Live-query capability exceeds the size limit")

    return {
        "capability": capability,
        "queryFingerprint": fingerprint,
        "expiresAt": expires_at * 1000,
    }
