"""Start the backend (uvicorn, :8000) and the frontend (Vite, :5173) together. Ctrl-C stops both.

    python scripts/dev.py              # then open http://localhost:5173
    python scripts/dev.py --load       # also load the seed-42 scenario once the backend is up

The Vite dev server proxies /api, /ws and /sim/* to the backend, so the browser talks to one origin.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_URL = "http://127.0.0.1:8000"


def stop(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":                      # npm spawns children: kill the whole tree
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_for_backend(proc, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise SystemExit(f"backend exited with code {proc.returncode}")
        try:
            urllib.request.urlopen(f"{BACKEND_URL}/health", timeout=1).read()
            return
        except OSError:
            time.sleep(0.3)
    raise SystemExit("backend did not come up within 60 s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--load", action="store_true", help="load the seed scenario once the backend is up")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--port", type=int, default=8000, help="backend port")
    args = ap.parse_args()
    global BACKEND_URL
    BACKEND_URL = f"http://127.0.0.1:{args.port}"

    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found: install Node.js 20+")
    if not (ROOT / "frontend" / "node_modules").exists():
        print("installing frontend dependencies ...")
        subprocess.run([npm, "install"], cwd=ROOT / "frontend", check=True)

    procs = []
    try:
        backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "safarset.api.app:app", "--port", str(args.port), "--reload"], cwd=ROOT / "backend")
        procs.append(backend)
        wait_for_backend(backend)
        if args.load:
            req = urllib.request.Request(f"{BACKEND_URL}/sim/load-scenario", data=json.dumps({"seed": args.seed}).encode(),
                                         headers={"content-type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
            print(f"scenario loaded (seed {args.seed})")
        env = dict(os.environ, SAFARSET_BACKEND=BACKEND_URL)
        procs.append(subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "frontend", env=env))
        print("\n  SafarSet:  http://localhost:5173   (backend docs: http://127.0.0.1:%d/docs)   Ctrl-C to stop\n" % args.port)
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("a process exited; stopping the other")
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(procs):
            stop(p)


if __name__ == "__main__":
    main()
