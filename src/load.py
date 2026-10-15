"""Load output/ into a Data Commons SQLite database with the official data container.

Equivalent to:
    docker run --rm --platform linux/amd64 --env-file env.list -e INPUT_DIR=/data -e OUTPUT_DIR=/data \
        -v <repo>/output:/data gcr.io/datcom-ci/datacommons-data:stable 2>&1 | tee output/load.log

What this wrapper adds:
- finds Docker Desktop on Windows when `docker` is not on PATH (per-user install), and puts its folder on
  PATH for the call so `docker-credential-desktop` is found when the image is pulled;
- deletes output/datacommons/ first, so every load starts from an empty database (re-running cannot
  duplicate anything);
- writes the log to output/load.log with secret values from env.list masked;
- exits non-zero unless the log contains "Runner finished successfully".
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
ENV_FILE = ROOT / "env.list"
LOG_FILE = OUTPUT_DIR / "load.log"
IMAGE = "gcr.io/datcom-ci/datacommons-data:stable"
CONTAINER_DIR = "/data"
SUCCESS = "Runner finished successfully"


def find_docker() -> str:
    found = shutil.which("docker")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    sys.exit("docker not found: install/start Docker Desktop, or add its resources\\bin folder to PATH")


def read_env_file() -> dict[str, str]:
    if not ENV_FILE.is_file():
        sys.exit(f"{ENV_FILE.name} not found: create it with DC_API_KEY=<your key> (see README)")
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if k != k.strip() or v != v.strip() or v[:1] in "\"'":
                sys.exit(f"{ENV_FILE.name}: '{k.strip()}' has spaces or quotes around the value; docker would keep them")
            env[k] = v
    if not env.get("DC_API_KEY"):
        sys.exit(f"{ENV_FILE.name}: DC_API_KEY is missing or empty")
    return env


def main() -> int:
    for name in ("observations.csv", "config.json", "variables.mcf"):
        if not (OUTPUT_DIR / name).is_file():
            sys.exit(f"output/{name} missing: run python src/pipeline.py first")

    env = read_env_file()
    secrets = [v for k, v in env.items() if v and any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD"))]

    docker = find_docker()
    run_env = dict(os.environ)
    run_env["PATH"] = str(Path(docker).parent) + os.pathsep + run_env.get("PATH", "")

    shutil.rmtree(OUTPUT_DIR / "datacommons", ignore_errors=True)
    cmd = [docker, "run", "--rm", "--platform", "linux/amd64",
           "--env-file", str(ENV_FILE),
           "-e", f"INPUT_DIR={CONTAINER_DIR}", "-e", f"OUTPUT_DIR={CONTAINER_DIR}",
           "-v", f"{OUTPUT_DIR}:{CONTAINER_DIR}", IMAGE]
    print("running:", " ".join(cmd[1:]), flush=True)

    ok = False
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=run_env,
                          text=True, encoding="utf-8", errors="replace") as proc, \
            LOG_FILE.open("w", encoding="utf-8", newline="\n") as log:
        for line in proc.stdout:
            for s in secrets:
                line = line.replace(s, "<redacted>")
            ok = ok or SUCCESS in line
            sys.stdout.write(line)
            log.write(line)
    print(f"log written to {LOG_FILE.relative_to(ROOT)}")
    if proc.returncode != 0 or not ok:
        print(f"LOAD FAILED (exit code {proc.returncode}; '{SUCCESS}' {'found' if ok else 'not found'})", file=sys.stderr)
        return 1
    db = OUTPUT_DIR / "datacommons" / "datacommons.db"
    print(f"load OK: {db.relative_to(ROOT)} ({db.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
