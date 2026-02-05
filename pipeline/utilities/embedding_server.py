"""Manage local embedding server process lifecycle."""

import logging
import os
import platform
import subprocess
import sys
import time
from typing import Optional, TextIO

import requests

logger = logging.getLogger(__name__)


class EmbeddingServerManager:
    """
    Manages the lifecycle of the Infinity embedding server.

    Features:
    - Automatic detection of existing server
    - Automatic startup on native execution (Mac/Linux)
    - Apple Silicon (MPS) acceleration support
    - Graceful shutdown
    """

    def __init__(
        self,
        model_id: str = "intfloat/multilingual-e5-large",
        port: int = 7997,
        batch_size: int = 32,
    ):
        self.model_id = os.getenv("DENSE_EMBEDDING_MODEL", model_id)
        self.port = int(os.getenv("INFINITY_PORT", port))
        self.batch_size = int(os.getenv("INFINITY_BATCH_SIZE", batch_size))
        # Default to localhost if not specified, but Docker execution might set this to
        # 'http://embedding-server:7997'
        self.base_url = os.getenv(
            "EMBEDDING_API_URL", f"http://localhost:{self.port}"
        ).rstrip("/")
        self.process: Optional[subprocess.Popen] = None
        self.log_file: Optional[TextIO] = None
        self._was_started_by_us = False

    def is_running(self) -> bool:
        """Check if the embedding server is running and healthy."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=1)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def start(self):
        """
        Start the embedding server if it's not already running.
        Does nothing if the server is reachable.
        """
        if self.is_running():
            logger.info("Embedding server already running at %s", self.base_url)
            return

        # If the URL is explicitly set to a remote host (not localhost/127.0.0.1),
        # we assume it's a managed service (like in Docker) and we shouldn't fail if it's down,
        # but we also can't start it.
        if "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            logger.warning(
                "Remote embedding server at %s is not reachable. "
                "Orchestrator cannot start remote servers.",
                self.base_url,
            )
            return

        logger.info(
            "Starting native Infinity embedding server for model: %s...",
            self.model_id,
        )

        # Use wrapper script to set process name (EvLab-EmbedServer)
        wrapper_script = "scripts/pipeline/run_embedding_server.py"
        if os.path.exists(wrapper_script):
            cmd = [
                sys.executable,
                wrapper_script,
                "v2",
                "--model-id",
                self.model_id,
                "--port",
                str(self.port),
                "--batch-size",
                str(self.batch_size),
            ]
        else:
            cmd = [
                "infinity_emb",
                "v2",
                "--model-id",
                self.model_id,
                "--port",
                str(self.port),
                "--batch-size",
                str(self.batch_size),
            ]

        # Apple Silicon optimization
        if sys.platform == "darwin" and platform.machine() == "arm64":
            logger.info("Detected Apple Silicon. Enabling MPS acceleration.")
            cmd.extend(["--device", "mps"])
        elif sys.platform == "linux":
            # Check for CUDA? For now default to auto which usually picks cuda if available
            pass

        # Determine log file path
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "embedding_server.log")

        try:
            # Open log file for subprocess output
            # pylint: disable=consider-using-with
            self.log_file = open(log_file_path, "a", encoding="utf-8")
            logger.info("Redirecting embedding server logs to %s", log_file_path)

            # Start process, redirect output to file
            self.process = subprocess.Popen(
                cmd, stdout=self.log_file, stderr=subprocess.STDOUT, text=True
            )
            self._was_started_by_us = True

            # Wait for startup
            logger.info("Waiting for embedding server to become healthy...")
            self._wait_for_healthy(timeout=60)
            logger.info("Embedding server started successfully.")

        except FileNotFoundError:
            logger.error(
                "infinity_emb not found. Please install with "
                "`pip install infinity-emb[optimum,server]`"
            )
            if hasattr(self, "log_file") and self.log_file:
                self.log_file.close()
            raise
        except Exception as exc:
            logger.error("Failed to start embedding server: %s", exc)
            if hasattr(self, "log_file") and self.log_file:
                self.log_file.close()
            self.stop()
            raise

    def stop(self):
        """Stop the server if it was started by this manager."""
        if self.process and self._was_started_by_us:
            logger.info("Stopping embedding server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Embedding server did not stop gracefully. Killing...")
                self.process.kill()
            self.process = None
            self._was_started_by_us = False

            # Close log file handle
            if hasattr(self, "log_file") and self.log_file:
                self.log_file.close()
                self.log_file = None

            logger.info("Embedding server stopped.")

    def _wait_for_healthy(self, timeout: int):
        """Poll health endpoint until success or timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_running():
                return

            # Check if process died
            if self.process and self.process.poll() is not None:
                raise RuntimeError(
                    "Embedding server process died unexpectedly. "
                    "Check logs/embedding_server.log for details."
                )

            time.sleep(1)

        raise TimeoutError("Timed out waiting for embedding server to start.")

    def get_client_url(self) -> str:
        """Return the embedding server base URL."""
        return self.base_url
