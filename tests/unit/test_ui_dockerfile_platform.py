"""The web app image builds for another platform without emulation.

Deployments build the web app image for the platform they run on (arm64 on
AWS, amd64 on Google Cloud and Azure), often on a machine of the other kind:
an Azure DevOps or GitHub agent is amd64, an Apple silicon Mac is arm64. The
built files are the same on every platform, so the build stage runs on the
build machine's own platform, and the nginx stage, the only one built for the
image's platform, runs no commands: any RUN there needs emulation.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "ui" / "frontend" / "Dockerfile.prod"


def _instructions(text: str) -> list[str]:
    """Return the Dockerfile's instructions, continuation lines joined, comments dropped."""
    instructions: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            current += line[:-1].rstrip() + " "
            continue
        instructions.append(current + line)
        current = ""
    return instructions


def _stages(text: str) -> list[list[str]]:
    """Split the instructions into stages, each starting with its FROM."""
    stages: list[list[str]] = []
    for instruction in _instructions(text):
        if instruction.upper().startswith("FROM "):
            stages.append([instruction])
        elif stages:
            stages[-1].append(instruction)
    return stages


def _keyword(instruction: str) -> str:
    return instruction.split(maxsplit=1)[0].upper()


STAGES = _stages(DOCKERFILE.read_text())


def test_stages_when_read_then_build_then_nginx():
    assert len(STAGES) == 2
    assert STAGES[0][0].endswith(" AS builder")
    assert " nginx:" in STAGES[1][0]


def test_nginx_stage_when_read_then_uses_slim_image():
    # The full nginx:alpine image adds modules this config doesn't load, and
    # with them libxml2, whose high-severity advisory failed the image scan.
    assert STAGES[1][0].split()[1] == "nginx:alpine-slim"


def test_build_stage_when_read_then_runs_on_build_machine_platform():
    assert STAGES[0][0].split()[1] == "--platform=$BUILDPLATFORM"


def test_nginx_stage_when_read_then_takes_platform_from_build_command():
    assert "--platform" not in STAGES[1][0]


def test_nginx_stage_when_read_then_runs_no_commands():
    assert [i for i in STAGES[1] if _keyword(i) == "RUN"] == []


@pytest.mark.parametrize("script", ["docker-entrypoint.sh", "render-nginx-conf.sh"])
def test_nginx_stage_when_read_then_copies_script_executable(script):
    assert f"COPY --chmod=0755 ui/frontend/{script} /{script}" in STAGES[1]


def test_nginx_stage_when_read_then_copies_build_output_from_builder():
    assert "COPY --from=builder /app/build /usr/share/nginx/html" in STAGES[1]


def test_instructions_when_continued_and_commented_then_joins_and_drops():
    text = "# note\nFROM a AS b\n\nRUN one \\\n    two\n# later\nCOPY x y\n"
    assert _instructions(text) == ["FROM a AS b", "RUN one two", "COPY x y"]
