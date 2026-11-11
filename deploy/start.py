"""Supervise loopback Go engine + one Python worker; fail together and restart."""
import os
import signal
import subprocess
import sys
import time

children = []
stopping = False


def stop(signum=None, frame=None):
    global stopping
    stopping = True
    for child in children:
        if child.poll() is None:
            child.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    crm_env = dict(os.environ, DATABASE_URL=os.environ["CRM_DATABASE_URL"],
                   AUTH_DATABASE_URL=os.environ["CRM_AUTH_DATABASE_URL"])
    children.append(subprocess.Popen(["/usr/local/bin/salescompel", "serve", "--addr", "127.0.0.1:8080", "--assets", ""], env=crm_env))
    children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
                                      "--workers", "1", "--no-access-log"], cwd="/app/modules/funnelhub/backend"))
    while not stopping and all(p.poll() is None for p in children):
        time.sleep(.5)
    code = 0 if stopping else 1
finally:
    stop()
    for child in children:
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
sys.exit(code)
