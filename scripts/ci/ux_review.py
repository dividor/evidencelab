"""Select the UX review's scope and prepare its CI-only administrator."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

FRONTEND = "ui/frontend/src/"
ADMIN_PREFIXES = (
    "components/admin/",
    "components/auth/",
    "components/documents/summary/",
    "components/layout/",
)
ADMIN_SHARED_FILES = {
    "App.css",
    "App.tsx",
    "index.css",
    "config.ts",
    "components/EcoLogitsLink.tsx",
    "components/TocModal.tsx",
    "components/brief/BriefLengthControl.tsx",
    "components/documents/MetadataModal.tsx",
    "components/documents/SortableHeader.tsx",
    "components/filters/SearchSettingsPanel.tsx",
    "hooks/useAuth.ts",
}
REVIEW_SETUP_FILES = {".github/review/ux-review.md", "scripts/ci/ux_review.py"}
MCP_TEMPLATE = Path(".github/review/ux/mcp.json")


def review_scope(paths: list[str]) -> str:
    """Classify changed paths for the guest and signed-in review browsers."""
    frontend = [
        path.removeprefix(FRONTEND) for path in paths if path.startswith(FRONTEND)
    ]
    if any(
        path in ADMIN_SHARED_FILES or path.startswith(ADMIN_PREFIXES)
        for path in frontend
    ):
        return "admin"
    if any(
        path in REVIEW_SETUP_FILES or path.startswith(".github/review/ux/")
        for path in paths
    ):
        return "admin-smoke"
    return "public" if frontend else "none"


def browser_config(
    template: dict[str, Any], storage_state: Path | None
) -> dict[str, Any]:
    """Give the admin browser its own authenticated context beside the guest."""
    servers = template["mcpServers"].copy()
    if storage_state is not None:
        guest = servers["playwright"]
        servers["playwright_admin"] = {
            **guest,
            "args": [*guest["args"], "--storage-state", str(storage_state)],
        }
    return {**template, "mcpServers": servers}


async def create_admin(email: str, password: str) -> None:
    """Create a verified account with the app's user manager on the CI database."""
    from ui.backend.auth.db import async_session_factory
    from ui.backend.auth.schemas import UserCreate
    from ui.backend.auth.users import UserManager, get_user_db

    user = UserCreate(
        email=email,
        password=password,
        first_name="UX",
        last_name="Review",
        is_active=True,
        is_superuser=True,
        is_verified=True,
    )
    async with async_session_factory() as session:
        async for user_db in get_user_db(session):
            await UserManager(user_db).create(user, safe=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scope", help="Read NUL-separated changed paths from stdin.")
    seed = commands.add_parser(
        "create-admin", help="Read the test password from stdin."
    )
    seed.add_argument("email")
    configure = commands.add_parser(
        "browser-config", help="Write the MCP config to stdout."
    )
    configure.add_argument("--storage-state", type=Path)
    args = parser.parse_args()
    if args.command == "scope":
        print(review_scope(sys.stdin.read().split("\0")))
    elif args.command == "create-admin":
        asyncio.run(create_admin(args.email, sys.stdin.read().rstrip("\n")))
    else:
        template = json.loads(MCP_TEMPLATE.read_text(encoding="utf-8"))
        print(json.dumps(browser_config(template, args.storage_state)))


if __name__ == "__main__":
    main()
