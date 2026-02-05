"""Environment setup for orchestrator workers."""

import os


def configure_thread_env() -> None:
    """Force single-threaded execution to avoid oversubscription."""
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["ONNXRUNTIME_INTRA_OP_NUM_THREADS"] = "1"


configure_thread_env()
