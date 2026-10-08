"""Keep the performance tunables' defaults consistent across the repo.

Each of these settings has a default in the application, a documented value
in ``.env.example``, and may be referenced by a compose file. They drifted
once: ``docker-compose.yml`` pinned ``MAX_CONCURRENT_SEARCHES`` to the old
default of 2, so raising the default in the code had no effect for anyone
running through compose — which is everyone.

These tests fail if any of those three disagree, and if the application
stops supplying a default at all, since an unset variable must never stop
the system from starting.
"""

import ast
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Variable -> the module that declares its default.
TUNABLES = {
    "MAX_CONCURRENT_SEARCHES": "ui/backend/routes/search.py",
    "MAX_CONCURRENT_RERANKS": "ui/backend/services/search_models.py",
    "MAX_CONCURRENT_REMOTE_RERANKS": "ui/backend/services/search_models.py",
    "POSTGRES_POOL_MIN": "pipeline/db/postgres_client_base.py",
    "POSTGRES_POOL_MAX": "pipeline/db/postgres_client_base.py",
    "AUTH_DB_POOL_SIZE": "ui/backend/auth/db.py",
    "AUTH_DB_MAX_OVERFLOW": "ui/backend/auth/db.py",
    "PRELOAD_RERANK_MODEL": "ui/backend/main.py",
}

COMPOSE_FILES = ["docker-compose.yml", "docker-compose.prod.yml"]


def _declared_default(source_path: str, var: str) -> str | None:
    """Return the literal default in os.environ.get(var, X) / os.getenv(var, X)."""
    tree = ast.parse((ROOT / source_path).read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) != 2:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"get", "getenv"}:
            continue
        key, default = node.args
        if isinstance(key, ast.Constant) and key.value == var:
            if isinstance(default, ast.Constant):
                return str(default.value)
    return None


def _env_example_value(var: str) -> str | None:
    for line in (ROOT / ".env.example").read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{var}="):
            return stripped.split("=", 1)[1].strip()
    return None


def _compose_pinned_defaults(var: str) -> list[tuple[str, str]]:
    """Every ``${VAR:-default}`` for this variable, as (file, default)."""
    found = []
    pattern = re.compile(r"\$\{" + re.escape(var) + r":-([^}]*)\}")
    for name in COMPOSE_FILES:
        path = ROOT / name
        if not path.exists():
            continue
        for match in pattern.finditer(path.read_text()):
            found.append((name, match.group(1)))
    return found


@pytest.mark.parametrize("var,source_path", sorted(TUNABLES.items()))
def test_tunable_when_unset_then_the_application_supplies_a_default(var, source_path):
    default = _declared_default(source_path, var)
    assert default is not None, (
        f"{var} has no default in {source_path}. An unset variable must not "
        f"stop the system from starting."
    )
    assert default != "", f"{var}'s default in {source_path} is empty."


@pytest.mark.parametrize("var,source_path", sorted(TUNABLES.items()))
def test_tunable_when_documented_then_env_example_matches_the_code(var, source_path):
    documented = _env_example_value(var)
    assert documented is not None, f"{var} is not documented in .env.example."
    assert documented == _declared_default(source_path, var), (
        f".env.example gives {var}={documented}, but {source_path} defaults to "
        f"{_declared_default(source_path, var)}. They must agree, or the "
        f"documented value silently changes behaviour."
    )


@pytest.mark.parametrize("var,source_path", sorted(TUNABLES.items()))
def test_tunable_when_compose_pins_a_default_then_it_matches_the_code(var, source_path):
    code_default = _declared_default(source_path, var)
    for compose_file, pinned in _compose_pinned_defaults(var):
        assert pinned == code_default, (
            f"{compose_file} pins {var} to {pinned!r} while {source_path} "
            f"defaults to {code_default!r}. A compose entry overrides .env, so "
            f"the stale value wins and changing the code default does nothing. "
            f"Either drop the entry (the service reads .env via env_file) or "
            f"keep both in step."
        )
