"""
Entry point for the Server Space Optimizer application.

Starts the FastAPI web server with uvicorn, serving both
the REST API and the web dashboard UI.
Usage: python run.py
"""

import os
import uvicorn
from server_space_optimizer.config import load_config


def main():
    """Load config and start the uvicorn web server."""
    config = load_config()
    host = os.environ.get("HOST", config.host)
    port = int(os.environ.get("PORT", config.port))

    print(f"Starting Server Space Optimizer on {host}:{port}")
    print(f"Dashboard: http://{host}:{port}/")
    print(f"API Docs:  http://{host}:{port}/docs")

    uvicorn.run(
        "server_space_optimizer.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
