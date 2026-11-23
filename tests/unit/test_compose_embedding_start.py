"""The embedding server gets time to download its model before it counts as unhealthy.

Its first start downloads the embedding model. Without a grace period the
health check gave it 150 s (30 checks, 5 s apart); CI's starts took 46 to 137 s
on 2026-11-21, and one went over, which stopped the whole integration stack.
Both compose files give the same grace period, and CI prints the services'
logs when the job fails, so the next failure shows its cause.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _embedding_healthcheck(compose_file):
    services = yaml.safe_load((ROOT / compose_file).read_text())["services"]
    return services["embedding-server"]["healthcheck"]


def test_dev_compose_when_read_then_embedding_server_has_a_grace_period():
    assert _embedding_healthcheck("docker-compose.yml")["start_period"] == "15m"


def test_compose_files_when_read_then_same_embedding_grace_period():
    dev = _embedding_healthcheck("docker-compose.yml")
    hub = _embedding_healthcheck("docker-compose.hub.yml")
    assert dev["start_period"] == hub["start_period"]


def test_ci_integration_job_when_it_fails_then_prints_the_embedding_servers_log():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    last = ci["jobs"]["integration-tests"]["steps"][-1]
    assert last["if"] == "failure()"
    assert "docker compose logs" in last["run"]
    assert "embedding-server" in last["run"]
