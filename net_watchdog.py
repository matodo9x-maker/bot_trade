import time
import socket
import subprocess
import sys
import os
import signal
from datetime import datetime

CHECK_HOST = "8.8.8.8"
CHECK_PORT = 53
CHECK_INTERVAL = 10

PYTHON = sys.executable
PID_FILE = "bot.pid"


def has_internet():
    try:
        socket.create_connection((CHECK_HOST, CHECK_PORT), timeout=3)
        return True
    except OSError:
        return False


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def restart_supervisor():
    log("RESTART SUPERVISOR")
    # Try to stop existing process (avoid duplicates)
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            os.remove(PID_FILE)
    except Exception:
        pass

    p = subprocess.Popen([PYTHON, "supervisor.py", "runtime"])
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(p.pid))
    except Exception:
        pass


def main():
    offline = False

    while True:
        online = has_internet()

        if not online and not offline:
            log("NETWORK DOWN")
            offline = True

        if online and offline:
            log("NETWORK RECOVERED → RESTART BOTS")
            restart_supervisor()
            offline = False

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
