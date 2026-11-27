"""Expose the packaged Heatmapper HTML as an MCP Apps resource."""

import hashlib
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.concurrency import run_in_threadpool

from mcp_server import oauth

HEATMAP_URI = "ui://evidencelab/heatmap.html"
HEATMAP_MIME_TYPE = "text/html;profile=mcp-app"


def heatmap_tool_metadata(*, app_only: bool = False) -> dict:
    ui = {
        "resourceUri": HEATMAP_URI,
        "visibility": ["app"] if app_only else ["model", "app"],
    }
    return {"ui": ui, "ui/resourceUri": HEATMAP_URI}


def resource_metadata(public_url: str) -> dict:
    domain = hashlib.sha256(public_url.encode()).hexdigest()[:32]
    return {"ui": {"csp": {}, "domain": f"{domain}.claudemcpcontent.com"}}


def load_heatmap_html() -> str:
    directory = Path(
        os.environ.get("MCP_APP_ASSET_DIR", Path(__file__).parent / "heatmap" / "dist")
    )
    try:
        return (directory / "heatmap.html").read_text(encoding="utf-8")
    except OSError:
        raise ValueError(
            "The Heatmapper app asset is unavailable. Build it using the MCP server admin guide."
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
