"""MVP Web 控制台：只读展示 + 触发现有链路。

不 import eda_agent；链路在子进程里跑，Web 只读 work/runs 下的 JSON/SVG。
"""
import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

ROOT = Path(r"D:\Code_all\AI-pcb")
LAB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119")
VENV_PY = LAB / ".venv" / "Scripts" / "python.exe"
PREVIEW_PY = Path(r"E:\python\py313\python.exe")
BUCK_PCB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-Collab-20261119\boards\Buck_Unrouted_Source.PcbDoc")
RUN_OUT = ROOT / "work" / "runs" / "p0_buck"
CHAIN_OUT = ROOT / "work" / "runs" / "chain"

app = FastAPI(title="AI PCB Auto-Placement")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "webapp" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/report")
def report() -> dict:
    return {
        "loop": read_json(RUN_OUT / "rule_loop_report.json"),
        "chain": read_json(CHAIN_OUT / "chain_report.json"),
        "preview": (RUN_OUT / "preview.svg").exists(),
    }


@app.get("/api/preview.svg")
def preview():
    path = RUN_OUT / "preview.svg"
    if not path.exists():
        return JSONResponse({"error": "no preview yet"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.post("/api/run")
def run() -> JSONResponse:
    chain = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_chain.py")],
        cwd=str(ROOT), capture_output=True, text=True, timeout=900,
    )
    if chain.returncode != 0:
        return JSONResponse(
            {"ok": False, "stdout": chain.stdout, "stderr": chain.stderr[-4000:]},
            status_code=500,
        )
    preview = subprocess.run(
        [str(PREVIEW_PY), str(ROOT / "scripts" / "render_preview.py"),
         "--pcb", str(BUCK_PCB),
         "--report", str(RUN_OUT / "rule_loop_report.json"),
         "--out", str(RUN_OUT / "preview.svg")],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    return JSONResponse({
        "ok": True,
        "stdout": chain.stdout,
        "preview_stdout": preview.stdout,
        "preview_stderr": preview.stderr[-1000:],
    })
