"""
Linux NAS Space Agent - Python version (optional).

If Python is available on the target Linux server, this agent provides
a richer scanning experience with incremental support. For servers
without Python, use the shell-script agent (space_agent.sh) instead.

Usage:
    python -m server_space_optimizer.agent.linux_agent \
        --server-url http://dashboard-host:8080 \
        --config /path/to/agent_config.yaml

Communication with the central dashboard is via REST API (JSON over HTTP),
compatible with any HTTP server (FastAPI, Tomcat, etc.).
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

import yaml

try:
    import httpx
    _HTTP_CLIENT = "httpx"
except ImportError:
    import urllib.request
    import urllib.error
    _HTTP_CLIENT = "urllib"

from server_space_optimizer.scanner.space_calculator import (
    scan_directory_recursive,
    format_size,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
)
logger = logging.getLogger("space-agent")


def _post_json(url: str, data: dict, timeout: int = 60) -> Optional[dict]:
    """
    Send a JSON POST request using httpx (preferred) or stdlib urllib.

    Returns the parsed JSON response or None on failure.
    """
    payload = json.dumps(data).encode("utf-8")

    if _HTTP_CLIENT == "httpx":
        try:
            resp = httpx.post(url, json=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("POST to %s failed: %s", url, exc)
            return None
    else:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.error("POST to %s failed: %s", url, exc)
            return None


def _get_json(url: str, timeout: int = 30) -> Optional[dict]:
    """Send a GET request and return the parsed JSON response."""
    if _HTTP_CLIENT == "httpx":
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("GET %s failed: %s", url, exc)
            return None
    else:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.error("GET %s failed: %s", url, exc)
            return None


def load_agent_config(config_path: str) -> dict:
    """Load agent configuration from a YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config or {}


def resolve_sub_app_path(nas_mount: str, sub_app: dict) -> str:
    """Resolve the absolute directory path for a sub-application."""
    if sub_app.get("is_dedicated_mount"):
        return sub_app["path"]
    return os.path.join(nas_mount, sub_app.get("path", sub_app["name"]))


def scan_and_report(
    server_url: str,
    server_name: str,
    server_host: str,
    nas_mount_path: str,
    sub_apps: list[dict],
) -> None:
    """Scan all sub-app directories and POST results to central server."""
    logger.info("Starting scan: server=%s (%s)", server_name, server_host)
    report_url = f"{server_url.rstrip('/')}/api/agent/report"
    scan_start = time.time()

    for sub_app in sub_apps:
        app_name = sub_app["name"]
        app_path = resolve_sub_app_path(nas_mount_path, sub_app)

        if not os.path.isdir(app_path):
            logger.warning("Directory not found: %s (%s)", app_name, app_path)
            continue

        logger.info("Scanning sub-app=%s path=%s", app_name, app_path)
        result = scan_directory_recursive(app_path, collect_file_info=True)

        # Build the JSON report payload
        report = {
            "server_name": server_name,
            "server_host": server_host,
            "sub_app_name": app_name,
            "directory_path": app_path,
            "total_size_bytes": result.total_size_bytes,
            "file_count": result.file_count,
            "dir_count": result.dir_count,
            "scan_timestamp": datetime.utcnow().isoformat(),
            "scan_type": "agent_full",
            "errors": result.errors[:50],
            "files": [
                {
                    "path": f.path,
                    "size_bytes": f.size_bytes,
                    "last_modified": f.last_modified.isoformat(),
                    "last_accessed": f.last_accessed.isoformat(),
                    "created_at": f.created_at.isoformat(),
                }
                for f in result.files[:5000]
            ],
        }

        logger.info(
            "Sub-app %s: %d files, %s",
            app_name, result.file_count, format_size(result.total_size_bytes),
        )

        resp = _post_json(report_url, report)
        if resp:
            logger.info("Report accepted: %s", resp.get("status", "ok"))
        else:
            logger.error("Failed to report metrics for %s", app_name)

    logger.info("Scan complete in %.2fs", time.time() - scan_start)


def run_agent(config_path: str, server_url: str) -> None:
    """Main agent loop: scan periodically and report to central server."""
    config = load_agent_config(config_path)
    server_name = config.get("server_name", "unknown")
    server_host = config.get("server_host", "localhost")
    nas_mount_path = config.get("nas_mount_path", "/mnt/nas")
    sub_apps = config.get("sub_apps", [])
    interval = config.get("scan_interval_minutes", 60)

    logger.info(
        "Agent: server=%s, host=%s, mount=%s, apps=%d, interval=%dm",
        server_name, server_host, nas_mount_path, len(sub_apps), interval,
    )

    # Health check the central server on startup
    health = _get_json(f"{server_url.rstrip('/')}/health")
    if health:
        logger.info("Connected to dashboard: %s", server_url)
    else:
        logger.warning("Dashboard unreachable at %s, retrying next cycle", server_url)

    while True:
        try:
            scan_and_report(
                server_url, server_name, server_host, nas_mount_path, sub_apps,
            )
        except Exception:
            logger.exception("Scan cycle failed, retrying next interval")

        logger.info("Sleeping %d minutes...", interval)
        time.sleep(interval * 60)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Linux NAS Space Agent (Python version)"
    )
    parser.add_argument(
        "--server-url", required=True,
        help="Central dashboard URL (e.g., http://dashboard:8080)",
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to agent_config.yaml",
    )
    args = parser.parse_args()
    run_agent(config_path=args.config, server_url=args.server_url)


if __name__ == "__main__":
    main()
