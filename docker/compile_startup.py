"""Docker build step (as root): start the API exactly as the container does, call /health once, stop.
Python writes bytecode for every module that startup imports, standard library included, and for nothing else, so
the runtime user (who can't write __pycache__) compiles nothing at start. Runs with PUBLIC_DEMO=true: /health makes
no database call."""
import threading
import time
import urllib.request

import uvicorn

server = uvicorn.Server(uvicorn.Config("scout.api.main:app", host="127.0.0.1", port=8099, access_log=False))
thread = threading.Thread(target=server.run)
thread.start()
deadline = time.time() + 60
while not server.started:
    if time.time() > deadline or not thread.is_alive():
        raise SystemExit("the API did not start")
    time.sleep(0.05)
urllib.request.urlopen("http://127.0.0.1:8099/health", timeout=10).read()
server.should_exit = True
thread.join()
