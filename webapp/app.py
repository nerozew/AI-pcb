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
WISP6_BOARD = ROOT / "work" / "runs" / "wisp6" / "boards" / "wisp-6_unrouted.PcbDoc"
BUCK_OUT = ROOT / "work" / "runs" / "p0_buck"
WISP6_OUT = ROOT / "work" / "runs" / "wisp6"
CHAIN_OUT = ROOT / "work" / "runs" / "chain"

app = FastAPI(title="AI PCB Auto-Placement")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def buck_view() -> dict:
    loop = read_json(BUCK_OUT / "rule_loop_report.json")
    if not loop:
        return {"board": "buck", "label": "Buck 6 器件", "empty": True}
    cands = []
    for c in loop.get("candidates", []):
        cfg = c.get("config", {})
        cands.append({
            "strategy": cfg.get("strategy", "?"),
            "label": cfg.get("strategy", "?"),
            "decap": cfg.get("decap_pull"),
            "moved": len(c.get("moves", [])),
            "fixed": loop.get("counts", {}).get("anchors", 3),
            "failed": c.get("failed", []),
            "new_drc": c.get("new_drc", 0),
            "hpwl_before": None,
            "hpwl_after": c.get("hpwl_after"),
            "seconds": c.get("seconds"),
            "hard_ok": c.get("hard_ok"),
            "soft_pass": c.get("soft_pass"),
            "soft_total": c.get("soft_total"),
            "soft": c.get("soft", []),
            "moves": c.get("moves", []),
        })
    best = loop.get("best", {})
    best_view = {
        **best,
        "moved": len(best.get("moves", [])),
        "fixed": loop.get("counts", {}).get("anchors", 3),
        "failed": best.get("failed", []),
        "soft": best.get("soft", []),
        "blocked": best.get("blocked", []),
    }
    return {
        "board": "buck",
        "label": "Buck 6 器件",
        "mode": "未布线源板",
        "source": str(BUCK_PCB),
        "counts": loop.get("counts", {"components": 9, "pads": 22, "movable": 6, "anchors": 3}),
        "anchors": loop.get("anchors", ["IC1", "J1", "J2"]),
        "movable": ["C1", "C2", "C3", "L1", "R1", "R2"],
        "baseline": loop.get("baseline", {"status": "fail", "violations": 6}),
        "rules_source": "configs/buck/rules.demo.json（demo 值；真实值需工程师审批）",
        "strategies": [
            {"key": "blocks", "label": "先分区再落位",
             "description": "先把电路分成功能块并排布，再在块内落位；更贴近人工习惯。", "enabled": True},
            {"key": "analytic", "label": "解析式线长布局",
             "description": "按连接关系把器件拉近、扩散，再做几何合法化；快。", "enabled": True},
        ],
        "candidates": cands,
        "best": best_view,
    }


def wisp6_view() -> dict:
    report = read_json(WISP6_OUT / "report.json")
    if not report:
        return {"board": "wisp6", "label": "wisp6 65 器件", "empty": True}
    return report


BOARDS = {
    "buck": {
        "label": "Buck 6 器件",
        "report": buck_view,
        "runner": ROOT / "scripts" / "run_chain.py",
        "preview": BUCK_OUT / "preview.svg",
        "pcb": BUCK_PCB,
        "report_path": BUCK_OUT / "rule_loop_report.json",
    },
    "wisp6": {
        "label": "wisp6 65 器件",
        "report": wisp6_view,
        "runner": ROOT / "scripts" / "run_wisp6_chain.py",
        "preview": WISP6_OUT / "preview.svg",
        "pcb": WISP6_BOARD,
        "report_path": WISP6_OUT / "report.json",
    },
}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "webapp" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/report")
def report(board: str = "wisp6") -> dict:
    cfg = BOARDS.get(board)
    if cfg is None:
        return JSONResponse({"error": f"unknown board {board}"}, status_code=404)
    data = cfg["report"]()
    data["preview"] = cfg["preview"].exists()
    return data


@app.get("/api/preview.svg")
def preview(board: str = "wisp6"):
    cfg = BOARDS.get(board)
    if cfg is None or not cfg["preview"].exists():
        return JSONResponse({"error": "no preview yet"}, status_code=404)
    return FileResponse(cfg["preview"], media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})


@app.post("/api/run")
def run(board: str = "wisp6") -> JSONResponse:
    cfg = BOARDS.get(board)
    if cfg is None:
        return JSONResponse({"ok": False, "error": f"unknown board {board}"}, status_code=404)
    chain = subprocess.run(
        [sys.executable, str(cfg["runner"])],
        cwd=str(ROOT), capture_output=True, text=True, timeout=1800,
    )
    if chain.returncode != 0:
        return JSONResponse(
            {"ok": False, "stdout": chain.stdout, "stderr": chain.stderr[-4000:]},
            status_code=500,
        )
    preview = subprocess.run(
        [str(PREVIEW_PY), str(ROOT / "scripts" / "render_preview.py"),
         "--pcb", str(cfg["pcb"]),
         "--report", str(cfg["report_path"]),
         "--out", str(cfg["preview"])],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    return JSONResponse({
        "ok": True,
        "stdout": chain.stdout,
        "preview_stdout": preview.stdout,
        "preview_stderr": preview.stderr[-1000:],
    })
