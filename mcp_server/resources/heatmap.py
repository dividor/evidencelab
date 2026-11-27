"""Expose the packaged Heatmapper HTML as an MCP Apps resource."""

import hashlib
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from starlette.concurrency import run_in_threadpool

from mcp_server import oauth
from mcp_server.resources.heatmap_branding import apply_heatmap_branding

logger = logging.getLogger(__name__)

HEATMAP_URI = "ui://evidencelab/heatmap.html"
HEATMAP_MIME_TYPE = "text/html;profile=mcp-app"


def heatmap_tool_metadata(*, app_only: bool = False) -> dict:
    ui = {
        "resourceUri": HEATMAP_URI,
        "visibility": ["app"] if app_only else ["model", "app"],
    }
    return {"ui": ui, "ui/resourceUri": HEATMAP_URI}


def resource_metadata(public_url: str) -> dict:
    url = urlsplit(public_url)
    if url.scheme != "https" or url.hostname in {None, "localhost", "127.0.0.1", "::1"}:
        return {"ui": {"csp": {}}}
    domain = hashlib.sha256(public_url.encode()).hexdigest()[:32]
    return {"ui": {"csp": {}, "domain": f"{domain}.claudemcpcontent.com"}}


def load_heatmap_html() -> str:
    packaged = os.getenv("MCP_APP_ASSET_DIR")
    directory = (
        Path(packaged) if packaged else Path(__file__).parent / "heatmap" / "dist"
    )
    stock_logo = (
        directory / "logo.png"
        if packaged
        else Path(__file__).parents[2] / "ui" / "frontend" / "public" / "logo.png"
    )
    try:
        html = (directory / "heatmap.html").read_text(encoding="utf-8")
    except OSError:
        raise ValueError(
            "The Heatmapper app asset is unavailable. Build it using the MCP server admin guide."
        ) from None
    try:
        return apply_heatmap_branding(html, stock_logo)
    except (OSError, ValueError):
        logger.exception("Could not load Heatmapper branding")
        raise ValueError(
            "The Heatmapper branding is invalid. Check the MCP server admin guide."
        ) from None


async def read_heatmap_html() -> str:
    return await run_in_threadpool(load_heatmap_html)


def register_heatmap_resource(server: FastMCP) -> None:
    server.resource(
        HEATMAP_URI,
        name="Heatmapper",
        description="Interactive Evidence Lab grid and document drill-down.",
        mime_type=HEATMAP_MIME_TYPE,
        meta=resource_metadata(oauth.public_mcp_url()),
    )(read_heatmap_html)
