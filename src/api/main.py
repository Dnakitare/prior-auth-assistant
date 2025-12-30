"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from src.api.routes import appeals, health, payers
from src.core.database import init_db

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Prior Authorization Assistant API")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning("Database initialization skipped", error=str(e))
    yield
    # Shutdown
    logger.info("Shutting down API")


app = FastAPI(
    title="Prior Authorization Assistant",
    description="AI-powered prior authorization appeals automation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(appeals.router, prefix="/api/v1", tags=["Appeals"])
app.include_router(payers.router, prefix="/api/v1", tags=["Payers"])
