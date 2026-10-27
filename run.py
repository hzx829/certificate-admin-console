"""One command installs dependencies, initializes data, builds and runs the app."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def run(args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, cwd=kwargs.pop("cwd", ROOT), **kwargs)


def prepare(build=True):
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12+ is required. Run this script with a supported Python interpreter.")
    env = ROOT / ".venv"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    requirements = ROOT / "requirements.lock.txt"
    if not requirements.exists():
        requirements = ROOT / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = env / ".requirements-sha256"
    if not marker.exists() or marker.read_text() != fingerprint:
        run([python, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements])
        marker.write_text(fingerprint)
    if build:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise SystemExit("Node.js 22.12+ (or 24+) and npm must be on PATH.")
        frontend = ROOT / "frontend"
        fingerprint = hashlib.sha256((frontend / "package-lock.json").read_bytes()).hexdigest()
        marker = frontend / "node_modules" / ".certificate-lock-sha256"
        if not marker.exists() or marker.read_text() != fingerprint:
            run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend)
            marker.write_text(fingerprint)
        run([npm, "run", "build"], cwd=frontend)
    return python


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=["start", "verify", "prepare", "seed-large"], default="start")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    python = prepare(build=args.command != "seed-large")
    if args.command == "verify":
        run([python, "-m", "tests.acceptance"])
    elif args.command == "seed-large":
        if args.database is None:
            parser.error("seed-large requires --database with a new file path")
        run([python, "-m", "app.seed", "--large", "--database", args.database.resolve()])
    elif args.command == "start":
        database = (args.database or ROOT / "data" / "demo.db").resolve()
        print(f"Certificate Console: http://127.0.0.1:{args.port}\nDatabase: {database}", flush=True)
        try:
            run([python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", args.port],
                env={**os.environ, "CERTIFICATE_DB":str(database)})
        except KeyboardInterrupt:
            pass
