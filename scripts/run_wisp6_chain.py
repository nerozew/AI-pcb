"""wisp6 65 器件：清铜副本 + 锚点 + eda_agent 布局，输出 UI 报告。

只在 work 副本上计算，不写 AD、不碰原板。
"""
import json
import os
from pathlib import Path

ROOT = Path(r"D:\Code_all\AI-pcb")
LAB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119")
os.environ["EDA_AGENT_WORKSPACE"] = str(LAB / "ipc")

from eda_agent.bridge.altium_bridge import get_bridge  # noqa: E402
from eda_agent.layout.drc import verdict  # noqa: E402
from eda_agent.layout.place.job import place_job  # noqa: E402
from eda_agent.layout.read_altium import read_live_board  # noqa: E402

BOARD = ROOT / "work" / "runs" / "wisp6" / "boards" / "wisp-6_unrouted.PcbDoc"
CONFIG = ROOT / "configs" / "wisp6" / "anchors.json"
OUT = ROOT / "work" / "runs" / "wisp6"


def vkey(v: dict) -> tuple:
    return (v.get("rule"), v.get("a"), v.get("b"))


def main() -> None:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    anchors = set(cfg["anchors"])

    bridge = get_bridge()
    bridge.send_command("pcb.focus_board", {"board_path": str(BOARD)}, timeout=120)
    board = read_live_board(str(BOARD))
    movable = sorted(c.ref for c in board.components if c.ref and c.ref not in anchors)

    base = verdict(board)
    base_rows = [v.as_dict() for v in base["violations"]]
    base_keys = {vkey(v) for v in base_rows}

    strategies = [
        {
            "key": "analytic",
            "label": "解析式线长布局",
            "description": "按连接关系把器件拉近、扩散，再做几何合法化；快，适合先看整体。",
            "enabled": True,
        },
        {
            "key": "blocks",
            "label": "先分区再落位",
            "description": "先把电路分成功能块并排布，再在块内落位；更贴近人工习惯，但 65 器件约 160s。",
            "enabled": False,
        },
    ]

    candidates = []
    for s in strategies:
        if not s["enabled"]:
            continue
        rep = place_job({"board": board, "parts": movable, "strategy": s["key"]})
        new = [v for v in rep["violations"] if vkey(v) not in base_keys]
        candidates.append({
            "strategy": s["key"],
            "label": s["label"],
            "description": s["description"],
            "moved": rep["summary"]["parts_moved"],
            "fixed": rep["summary"]["parts_fixed"],
            "failed": rep["summary"]["failed"],
            "new_drc": len(new),
            "new_drc_rows": new[:5],
            "hpwl_before": rep["summary"]["hpwl_before"],
            "hpwl_after": rep["summary"]["hpwl_after"],
            "seconds": rep["summary"]["seconds"],
            "moves": rep["moves"],
        })

    best = sorted(candidates, key=lambda c: (len(c["failed"]), c["new_drc"], c["hpwl_after"]))[0]
    best["blocked"] = []

    report = {
        "board": "wisp6",
        "label": "wisp6 65 器件",
        "mode": "清铜副本（原板不动）",
        "source": str(BOARD),
        "counts": {
            "components": len(board.components),
            "pads": len(board.pads),
            "nets": len(board.nets()),
            "movable": len(movable),
            "anchors": len(anchors),
        },
        "anchors": sorted(anchors),
        "movable": movable,
        "baseline": {"status": base["status"], "violations": len(base_rows)},
        "rules_source": "wisp6 尚未配置软规则集；当前只跑锚点 + 几何/DRC 硬约束。",
        "strategies": strategies,
        "candidates": candidates,
        "best": best,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"board={board.name} components={len(board.components)} "
          f"movable={len(movable)} anchors={len(anchors)} baseline={len(base_rows)}")
    for c in candidates:
        print(f"[{c['strategy']}] moved={c['moved']} fixed={c['fixed']} "
              f"failed={len(c['failed'])} new_drc={c['new_drc']} "
              f"hpwl={c['hpwl_before']}->{c['hpwl_after']} sec={c['seconds']}")
    print("wrote", OUT / "report.json")


if __name__ == "__main__":
    main()
