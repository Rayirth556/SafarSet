"""Windows only. Start scripts/dev.py in its own console, press a REAL Ctrl-C in that console, and check both servers stop and both ports are free.

Run: python scripts/ctrlc_test.py  (exit code 0 = both servers stopped and both ports are free). Some harnesses start processes with
Ctrl-C ignored (inherited), a real terminal does not, so the launcher re-enables it first.

A console Ctrl-C is delivered by attaching to the target console (AttachConsole) and calling GenerateConsoleCtrlEvent, which is what a
user pressing the keys does: every process in that console, including uvicorn and Vite, receives it.
"""
import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def listening(port):
    """True if anything accepts connections on the port, over IPv4 or IPv6 (Vite binds to localhost, which is ::1 here)."""
    for host in ("127.0.0.1", "::1"):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, port)) == 0:
                return True
    return False


def send_ctrl_c(pid):
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        raise OSError(f"AttachConsole failed: {ctypes.get_last_error()}")
    k32.SetConsoleCtrlHandler(None, True)          # this helper ignores the event itself
    k32.GenerateConsoleCtrlEvent(0, 0)             # CTRL_C_EVENT to every process on the console
    time.sleep(1)
    k32.FreeConsole()
    k32.SetConsoleCtrlHandler(None, False)


def main():
    log = open(os.environ["TEMP"] + r"\ctrlc_dev.log", "w")
    # This harness starts processes with Ctrl-C ignored (inherited), unlike a real terminal; re-enable it first, then run the real script unchanged.
    launcher = ("import ctypes, runpy; ctypes.WinDLL('kernel32').SetConsoleCtrlHandler(None, False); "
                f"runpy.run_path(r'{ROOT / 'scripts' / 'dev.py'}', run_name='__main__')")
    proc = subprocess.Popen([sys.executable, "-c", launcher], cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 60 and not (listening(8000) and listening(5173)):
        time.sleep(0.5)
    print("both ports up:", listening(8000), listening(5173), f"after {time.time() - t0:.1f}s")
    time.sleep(2)
    send_ctrl_c(proc.pid)
    t1 = time.time()
    while time.time() - t1 < 30 and (proc.poll() is None or listening(8000) or listening(5173)):
        time.sleep(0.3)
    print(f"dev.py exit code: {proc.poll()} after {time.time() - t1:.1f}s")
    print("port 8000 free:", not listening(8000), "| port 5173 free:", not listening(5173))
    ok = proc.poll() is not None and not listening(8000) and not listening(5173)       # judged BEFORE any cleanup
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


main()
