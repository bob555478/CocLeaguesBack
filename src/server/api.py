from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse

from .db import ensure_cwl_leagues_table
from .routers import (
    accounts_router,
    coc_router,
    leagues_router,
    neon_router,
)

OPENAPI_TAGS = [
    {
        "name": "1. Clash of Clans (CoC) API",
        "description": (
            "Proxy routes to `https://api.clashofclans.com/v1` that attach the server's "
            "`Authorization: Bearer <COC_API_TOKEN>` header and avoid browser CORS restrictions."
        ),
    },
    {
        "name": "2. CWL League Organization (Lakebase Postgres)",
        "description": (
            "Read and write 7-day CWL schedules in the `cwl_leagues` table in Lakebase Postgres. "
            "Every mutating route returns `pg_current_xact_id()::text AS txid` in a single round trip "
            "for Neon Realtime `awaitTxId()`."
        ),
    },
    {
        "name": "3. Neon Realtime & Auth / System",
        "description": (
            "Seal live SQL queries for Neon Realtime WebSocket subscriptions and check "
            "Lakebase Postgres, Neon Auth JWKS, and Neon Realtime status."
        ),
    },
    {
        "name": "4. User Linked In-Game Accounts (user_ingame_accounts)",
        "description": (
            "Link an online Neon Auth user to one or many Clash of Clans in-game players and their "
            "assigned clans, enforcing that every online user has at least 1 linked in-game account "
            "and can switch between them easily."
        ),
    },
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await ensure_cwl_leagues_table()
    except Exception:
        # Don't block server startup if DB is temporarily unreachable
        pass
    yield


app = FastAPI(
    title="CoC Leagues Backend API",
    description=(
        "Backend API for **Clash of Clans CWL League Organization**, backed by "
        "**Lakebase Postgres**, **Neon Auth** (JWKS verification), and **Neon Realtime** (live SQL query sealing)."
    ),
    version="1.0.0",
    openapi_tags=OPENAPI_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "defaultModelsExpandDepth": 2,
    },
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "detail": exc.detail},
    )


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/docs")


@app.get("/swagger", include_in_schema=False)
async def swagger_ui_alias():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_ui_parameters=app.swagger_ui_parameters,
    )


# Register modular API routers
app.include_router(coc_router)
app.include_router(leagues_router)
app.include_router(neon_router)
app.include_router(accounts_router)
