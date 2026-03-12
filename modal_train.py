"""
Modal entrypoints for autoresearch training and one-time cache preparation.

The agent-facing interface stays shell-based:

    modal run modal_train.py > run.log 2>&1

This runs ``train.py`` inside a fresh A100-backed container and streams the
container logs back to the caller. The autoresearch cache still lives at
``~/.cache/autoresearch`` inside the container, but that path is backed by a
named Modal Volume so the data and tokenizer persist across runs.

To initialize the shared cache once, run:

    modal run modal_train.py::prepare_data
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import modal


APP_NAME = "autoresearch"
PROJECT_ROOT = Path(__file__).resolve().parent
UV_PROJECT_DIR = os.path.relpath(PROJECT_ROOT, Path.cwd())
REMOTE_PROJECT_ROOT = "/root/autoresearch"
REMOTE_CACHE_ROOT = "/root/.cache/autoresearch"
DEFAULT_VOLUME_NAME = os.environ.get("AUTORESEARCH_MODAL_VOLUME", "autoresearch-cache")

PROJECT_IGNORE_PATTERNS = (
    ".git",
    ".venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "run.log",
    "results.tsv",
    "worktrees",
    "queue",
    "results",
)

app = modal.App(APP_NAME)
cache_volume = modal.Volume.from_name(DEFAULT_VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_sync(uv_project_dir=UV_PROJECT_DIR)
    .workdir(REMOTE_PROJECT_ROOT)
    .add_local_dir(
        str(PROJECT_ROOT),
        remote_path=REMOTE_PROJECT_ROOT,
        ignore=PROJECT_IGNORE_PATTERNS,
    )
)


def _run_script(script_name: str, extra_args: Sequence[str] = ()) -> None:
    """Run a repo script in the container and stream its output to Modal logs."""
    command = [sys.executable, script_name, *extra_args]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    completed = subprocess.run(command, cwd=REMOTE_PROJECT_ROOT, env=env, check=False)
    if completed.returncode != 0:
        joined = " ".join(command)
        raise RuntimeError(f"{joined} exited with code {completed.returncode}")


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=20 * 60,
    # One invocation per container avoids reusing a stale repo snapshot.
    single_use_containers=True,
    volumes={REMOTE_CACHE_ROOT: cache_volume},
)
def run_train() -> None:
    """Run ``train.py`` on a dedicated A100 container."""
    cache_volume.reload()
    _run_script("train.py")


@app.function(
    image=image,
    timeout=2 * 60 * 60,
    single_use_containers=True,
    volumes={REMOTE_CACHE_ROOT: cache_volume},
)
def prepare_data(num_shards: int = 10, download_workers: int = 8) -> None:
    """Populate the shared cache volume by running the existing prep pipeline."""
    cache_volume.reload()

    args = [
        "--num-shards",
        str(num_shards),
        "--download-workers",
        str(download_workers),
    ]
    _run_script("prepare.py", args)

    cache_volume.commit()


@app.local_entrypoint()
def main() -> None:
    """Run the training job remotely and stream logs back to the local shell."""
    run_train.remote()
