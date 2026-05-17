"""
Main FastAPI application for the Server Space Optimizer.

Serves the web UI dashboard and REST API endpoints for monitoring
NAS mount space usage across multiple Linux servers. Starts the
background scan scheduler on application startup.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from server_space_optimizer.api.routes import router as api_router, set_dependencies
from server_space_optimizer.config import load_config
from server_space_optimizer.models.database import init_database
from server_space_optimizer.scheduler.scan_scheduler import ScanScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Paths for static files and templates
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Global scheduler reference for lifecycle management
_scheduler: ScanScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup/shutdown events.

    Initializes the database, loads server configuration, starts the
    scan scheduler on startup, and stops the scheduler on shutdown.
    """
    global _scheduler

    # Load configuration from YAML
    config_path = os.environ.get("CONFIG_PATH", None)
    config = load_config(config_path)

    logger.info(
        "Loaded configuration: %d servers, scan interval=%d min",
        len(config.servers),
        config.scan_interval_minutes,
    )

    # Initialize database
    session_factory = init_database(config.database_path)
    logger.info("Database initialized at: %s", config.database_path)

    # Create and start the scan scheduler
    _scheduler = ScanScheduler(config)

    # Inject dependencies into API routes
    set_dependencies(session_factory, _scheduler, config)

    # Start the background scan scheduler
    _scheduler.start()
    logger.info("Scan scheduler started")

    yield

    # Shutdown: stop the scheduler
    if _scheduler:
        _scheduler.stop()
        logger.info("Scan scheduler stopped")


# Create the FastAPI application
app = FastAPI(
    title="Server Space Optimizer",
    description=(
        "Linux NAS Mount Space Monitoring and Optimization Tool. "
        "Calculates space per sub-application with incremental 60-minute "
        "refresh, purge eligibility reporting, and volume growth predictions."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup Jinja2 templates for the web UI
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API routes
app.include_router(api_router)


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Serve the main dashboard HTML page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/purge", response_class=HTMLResponse)
async def purge_page(request: Request):
    """Serve the purge eligibility report page."""
    return templates.TemplateResponse("purge.html", {"request": request})


@app.get("/predictions", response_class=HTMLResponse)
async def predictions_page(request: Request):
    """Serve the volume growth predictions page."""
    return templates.TemplateResponse("predictions.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "server-space-optimizer",
        "version": "1.0.0",
    }
