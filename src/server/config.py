import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env.local first (written by `neon link` / `neon env pull`), then .env
load_dotenv(ROOT_DIR / ".env.local", override=False)
load_dotenv(ROOT_DIR / ".env", override=False)


def get_database_url(unpooled: bool = False) -> str:
    if unpooled:
        url = os.getenv("DATABASE_URL_UNPOOLED") or os.getenv("DATABASE_URL")
    else:
        url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_UNPOOLED")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured in environment or .env.local")
    return url


def get_database_name() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_UNPOOLED") or ""
    if url:
        parsed = urlparse(url)
        db_name = parsed.path.lstrip("/")
        if db_name:
            return db_name
    return os.getenv("PGDATABASE", "neondb")


def get_coc_api_token() -> str | None:
    return os.getenv("COC_API_TOKEN")


def get_coc_api_base_url() -> str:
    return (os.getenv("COC_API_BASE_URL") or "https://api.clashofclans.com/v1").rstrip("/")


def get_neon_auth_base_url() -> str | None:
    return os.getenv("NEON_AUTH_BASE_URL")


def get_neon_auth_jwks_url() -> str | None:
    jwks_url = os.getenv("NEON_AUTH_JWKS_URL")
    if jwks_url:
        return jwks_url
    base_url = get_neon_auth_base_url()
    if base_url:
        return f"{base_url.rstrip('/')}/.well-known/jwks.json"
    return None


def get_neon_realtime_secret() -> str | None:
    return os.getenv("NEON_REALTIME_SECRET")


def get_neon_realtime_url() -> str | None:
    return os.getenv("NEON_REALTIME_URL")


def normalize_clan_tag(tag: str) -> str:
    """Normalize a Clash of Clans tag to uppercase with a leading '#'."""
    from urllib.parse import unquote

    cleaned = unquote(tag or "").strip().upper()
    if not cleaned:
        raise ValueError("Clan tag cannot be empty")
    if not cleaned.startswith("#"):
        cleaned = f"#{cleaned}"
    return cleaned
