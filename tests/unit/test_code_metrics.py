"""Tests for scripts/quality/code_metrics.py.

Requires ``lizard`` which is a dev-only dependency (not installed in CI).
The entire module is skipped when lizard is unavailable.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "quality"))

lizard = pytest.importorskip("lizard", reason="lizard not installed (dev-only)")

from code_metrics import discover_files, should_skip  # noqa: E402


class TestShouldSkip:
    """Tests for the should_skip function."""

    def test_skips_node_modules(self):
        path = Path("ui/frontend/node_modules/eslint/index.js")
        assert should_skip(path, {"node_modules"}) is True

    def test_skips_venv(self):
        path = Path(".venv/lib/python3.11/site-packages/foo.py")
        assert should_skip(path, {".venv"}) is True

    def test_allows_normal_path(self):
        path = Path("pipeline/orchestrator/core_impl.py")
        assert should_skip(path, {"node_modules", ".venv"}) is False

    def test_skips_nested_excluded_dir(self):
        path = Path("some/deep/node_modules/package/index.js")
        assert should_skip(path, {"node_modules"}) is True

    def test_empty_exclude_set(self):
        path = Path("node_modules/foo.js")
        assert should_skip(path, set()) is False


class TestDiscoverFiles:
    """Tests for the discover_files function."""

    def test_excludes_node_modules_before_stat(self, tmp_path):
        """Ensure node_modules is skipped before calling stat().

        This is the fix for the OSError: [Errno 34] crash when stat()
        fails on certain node_modules files.
        """
        # Create a normal Python file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("print('hello')")

        # Create a node_modules directory with a JS file
        nm_dir = tmp_path / "node_modules" / "pkg"
        nm_dir.mkdir(parents=True)
        (nm_dir / "index.js").write_text("module.exports = {}")

        files = discover_files([str(tmp_path)], {"node_modules", ".venv"})

        # Should find app.py but NOT the node_modules file
        filenames = [f.name for f in files]
        assert "app.py" in filenames
        assert "index.js" not in filenames

    def test_excludes_node_modules_even_when_stat_would_fail(self, tmp_path):
        """Verify that files in excluded dirs are skipped before stat().

        Simulates the original crash by patching is_file to raise
        OSError for paths inside node_modules.
        """
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("print('hello')")

        nm_dir = tmp_path / "node_modules" / "pkg"
        nm_dir.mkdir(parents=True)
        bad_file = nm_dir / "bad.js"
        bad_file.write_text("x")

        original_is_file = Path.is_file

        def patched_is_file(self):
            if "node_modules" in self.parts:
                raise OSError(34, "Result too large", str(self))
            return original_is_file(self)

        with patch.object(Path, "is_file", patched_is_file):
            # This should NOT raise because should_skip runs first
            files = discover_files([str(tmp_path)], {"node_modules", ".venv"})

        filenames = [f.name for f in files]
        assert "app.py" in filenames
        assert "bad.js" not in filenames

    def test_discovers_python_files(self, tmp_path):
        (tmp_path / "foo.py").write_text("x = 1")
        (tmp_path / "bar.txt").write_text("not code")

        files = discover_files([str(tmp_path)], set())
        filenames = [f.name for f in files]
        assert "foo.py" in filenames
        assert "bar.txt" not in filenames

    def test_discovers_js_and_ts_files(self, tmp_path):
        (tmp_path / "app.js").write_text("const x = 1")
        (tmp_path / "comp.tsx").write_text("export default function() {}")

        files = discover_files([str(tmp_path)], set())
        filenames = [f.name for f in files]
        assert "app.js" in filenames
        assert "comp.tsx" in filenames

    def test_single_file_path(self, tmp_path):
        f = tmp_path / "single.py"
        f.write_text("x = 1")

        files = discover_files([str(f)], set())
        assert len(files) == 1
        assert files[0].name == "single.py"

    def test_nonexistent_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            discover_files([str(tmp_path / "nope")], set())
