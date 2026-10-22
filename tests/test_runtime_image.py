"""The API image's runtime: no pandas or numpy on the import path, uv only at build time, bytecode compiled at build."""
import json
import subprocess
import sys

from scout.data.manifest import ROOT


def test_importing_the_app_loads_neither_pandas_nor_numpy():
    code = "import json, sys, scout.api.main; print(json.dumps(sorted(m for m in ('pandas', 'numpy') if m in sys.modules)))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert json.loads(out) == []


def test_dockerfile_runs_from_the_venv_with_build_time_bytecode():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--no-editable" in dockerfile and "rm -rf /app/scout" in dockerfile  # our modules installed, not shadowed
    assert "UV_COMPILE_BYTECODE" not in dockerfile and "compile_startup.py" in dockerfile
    assert "COPY --from=" not in dockerfile and "--mount=from=uv" in dockerfile  # uv mounted at build, not copied
    cmd = json.loads(dockerfile.rsplit("CMD ", 1)[1])
    assert cmd[0] == "/app/.venv/bin/uvicorn" and "uv" not in cmd[:2]
