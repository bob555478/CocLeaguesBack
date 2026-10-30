from .accounts import router as accounts_router
from .coc import router as coc_router
from .leagues import router as leagues_router
from .neon import router as neon_router

__all__ = [
    "coc_router",
    "leagues_router",
    "neon_router",
    "accounts_router",
]
