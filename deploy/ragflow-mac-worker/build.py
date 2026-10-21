"""Build from native temporary storage to exclude external-volume AppleDouble metadata."""
import subprocess
import tempfile
from pathlib import Path


source = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="perclip-worker-build-") as directory:
    for name in ("Dockerfile", "worker.patch"):
        (Path(directory) / name).write_bytes((source / name).read_bytes())
    subprocess.run([
        "docker", "build", "--platform", "linux/amd64", "-t",
        "perclip/ragflow-mac-worker:20261015-hardening", directory,
    ], check=True)
