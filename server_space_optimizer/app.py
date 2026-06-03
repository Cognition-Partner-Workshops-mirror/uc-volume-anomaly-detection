"""
Main FastAPI application for Volume Anomaly Detection & Storage Forecaster.

Serves the web UI dashboard and REST API endpoints for monitoring
NAS mount space usage across multiple Linux servers. Starts the
background scan scheduler on application startup. Includes user
authentication with login/signup pages.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Cookie, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from server_space_optimizer.api.routes import router as api_router, set_dependencies
from server_space_optimizer.config import load_config
from server_space_optimizer.models.database import (
    User,
    get_session,
    hash_password,
    init_database,
)
from server_space_optimizer.auth.auth_manager import authenticate_user, create_user
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
# Global session factory for auth routes
_session_factory = None
# Global config reference for template access
_app_config = None

# Product name shown on the login page — renamed from VADSF to NAS Capacity Pulse
PRODUCT_NAME = "NAS Capacity Pulse"
# Punchline / tagline displayed below product name
PRODUCT_TAGLINE = "Volume Anomaly Detection & Storage Forecaster"


def _get_current_user(session_token: str) -> dict | None:
    """
    Validate session token and return user info.

    Uses a simple token format: 'user:<username>' signed check.
    For production, replace with JWT or itsdangerous signed cookies.
    """
    if not session_token or not _session_factory:
        return None
    try:
        # Token format: "<username>:<hash_prefix>"
        parts = session_token.split(":", 1)
        if len(parts) != 2:
            return None
        username = parts[0]
        token_hash = parts[1]
        db = get_session(_session_factory)
        user = db.query(User).filter(User.username == username).first()
        db.close()
        if user and user.password_hash[:16] == token_hash:
            return {
                "username": user.username,
                "email": user.email,
                "display_name": user.display_name or user.username,
            }
    except Exception:
        pass
    return None


def _make_session_token(user: User) -> str:
    """Create a session token string from a User object."""
    return f"{user.username}:{user.password_hash[:16]}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for startup/shutdown events.

    Initializes the database, loads server configuration, starts the
    scan scheduler on startup, and stops the scheduler on shutdown.
    """
    global _scheduler, _session_factory, _app_config

    # Load configuration from YAML
    config_path = os.environ.get("CONFIG_PATH", None)
    config = load_config(config_path)
    _app_config = config

    logger.info(
        "Loaded configuration: %d servers, scan interval=%d min",
        len(config.servers),
        config.scan_interval_minutes,
    )

    # Initialize database
    session_factory = init_database(config.database_path)
    _session_factory = session_factory
    logger.info("Database initialized at: %s", config.database_path)

    # Create and start the scan scheduler (pass session_factory to share one engine)
    _scheduler = ScanScheduler(config, session_factory=session_factory)

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


# Create the FastAPI application with updated product name
app = FastAPI(
    title=PRODUCT_NAME,
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


# ---- Authentication pages ----

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    """Serve the login page."""
    return templates.TemplateResponse(
        name="login.html",
        request=request,
        context={"product_name": PRODUCT_NAME, "product_tagline": PRODUCT_TAGLINE, "error": error},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission."""
    if not _session_factory:
        return RedirectResponse("/login?error=System+not+ready", status_code=303)

    db = get_session(_session_factory)
    user = authenticate_user(db, username, password)

    if not user:
        db.close()
        return templates.TemplateResponse(
            name="login.html",
            request=request,
            context={
                "product_name": PRODUCT_NAME,
                "product_tagline": PRODUCT_TAGLINE,
                "error": "Invalid username or password",
            },
        )

    # Build session token before closing DB to avoid detached instance error
    token = _make_session_token(user)
    db.close()

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key="session_token", value=token, httponly=True, max_age=86400
    )
    return response


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, error: str = "", success: str = ""):
    """Serve the signup page."""
    return templates.TemplateResponse(
        name="signup.html",
        request=request,
        context={
            "product_name": PRODUCT_NAME,
            "product_tagline": PRODUCT_TAGLINE,
            "error": error,
            "success": success,
        },
    )


@app.post("/signup")
async def signup_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(default=""),
):
    """Handle signup form submission. Default password is welcome123."""
    if not _session_factory:
        return RedirectResponse("/signup?error=System+not+ready", status_code=303)

    db = get_session(_session_factory)
    # Use provided password or default 'welcome123'
    pw = password if password else "welcome123"
    user = create_user(db, username, email, password=pw)

    if not user:
        db.close()
        return templates.TemplateResponse(
            name="signup.html",
            request=request,
            context={
                "product_name": PRODUCT_NAME,
                "product_tagline": PRODUCT_TAGLINE,
                "error": "Username or email already exists",
                "success": "",
            },
        )

    db.close()
    return RedirectResponse(
        "/login?error=Account+created+successfully.+Please+login.",
        status_code=303,
    )


@app.get("/logout")
async def logout():
    """Log out and clear session cookie."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session_token")
    return response


# ---- Protected pages (require login) ----

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    session_token: str = Cookie(default=""),
):
    """Serve the main dashboard HTML page (requires login)."""
    user = _get_current_user(session_token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        name="dashboard.html",
        request=request,
        context={"user": user, "product_name": PRODUCT_NAME, "product_tagline": PRODUCT_TAGLINE},
    )


@app.get("/purge", response_class=HTMLResponse)
async def purge_page(
    request: Request,
    session_token: str = Cookie(default=""),
):
    """Serve the purge eligibility report page."""
    user = _get_current_user(session_token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        name="purge.html",
        request=request,
        context={"user": user, "product_name": PRODUCT_NAME, "product_tagline": PRODUCT_TAGLINE},
    )


@app.get("/predictions", response_class=HTMLResponse)
async def predictions_page(
    request: Request,
    session_token: str = Cookie(default=""),
):
    """Serve the volume growth predictions page."""
    user = _get_current_user(session_token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        name="predictions.html",
        request=request,
        context={"user": user, "product_name": PRODUCT_NAME, "product_tagline": PRODUCT_TAGLINE},
    )


@app.get("/extensions", response_class=HTMLResponse)
async def extensions_page(
    request: Request,
    session_token: str = Cookie(default=""),
):
    """Serve the file extensions analysis page."""
    user = _get_current_user(session_token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        name="extensions.html",
        request=request,
        context={"user": user, "product_name": PRODUCT_NAME, "product_tagline": PRODUCT_TAGLINE},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    session_token: str = Cookie(default=""),
):
    """Serve the sub-app configuration management page."""
    user = _get_current_user(session_token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        name="settings.html",
        request=request,
        context={"user": user, "product_name": PRODUCT_NAME, "product_tagline": PRODUCT_TAGLINE},
    )


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "volume-anomaly-detection",
        "version": "1.0.0",
    }
