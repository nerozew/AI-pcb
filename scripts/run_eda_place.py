"""用已安装的 eda_agent 对 Buck 未布线源板做只读布局复现。

不写 AD、不保存工程；只 set_active_document 聚焦到已打开的板，然后读取、
调用 eda_agent 的 place_job（blocks / analytic），把结果写到 work/runs/p0_buck。
"""
import json
import os
from pathlib import Path

LAB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119")
BOARD = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-Collab-20261119\boards\Buck_Unrouted_Source.PcbDoc")
PARTS = ["C1", "C2", "C3", "L1", "R1", "R2"]
OUT = Path(r"D:\Code_all\AI-pcb\work\runs\p0_buck")

# 必须与 AD26 里脚本读到的 workspace 指针一致
os.environ["EDA_AGENT_WORKSPACE"] = str(LAB / "ipc")

from eda_agent.bridge.altium_bridge import get_bridge  # noqa: E402
from eda_agent.layout.read_altium import read_live_board  # noqa: E402
from eda_agent.layout.drc import verdict  # noqa: E402
from eda_agent.layout.place.job import place_job  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
bridge = get_bridge()
focus = bridge.send_command("application.set_active_document", {"file_path": str(BOARD)})
print("focus:", json.dumps(focus, ensure_ascii=False)[:400])

board = read_live_board(str(BOARD))
print(f"board: {board.name}  components={len(board.components)}  pads={len(board.pads)}")

# 优先使用编译后的生效规则；没有则回退到实验用的 PARTS
rules_file = OUT / "effective_rules.json"
if rules_file.exists():
    effective = json.loads(rules_file.read_text(encoding="utf-8"))
    parts = effective.get("parts") or PARTS
    print(f"rules: parts={len(parts)} hard={len(effective.get('hard_rules', []))} "
          f"review_required={len(effective.get('review_required', []))} "
          f"conflicts={len(effective.get('conflicts', []))}")
else:
    parts = PARTS
    print("rules: 未找到 effective_rules.json，使用实验 PARTS")

# 原板基线：这些违规在移动前就存在，不应算到布局头上
base = verdict(board)
base_rows = [v.as_dict() for v in base["violations"]]
base_keys = {(v["rule"], v["a"], v["b"]) for v in base_rows}
(OUT / "baseline.json").write_text(
    json.dumps({"status": base["status"], "violations": base_rows}, ensure_ascii=False, indent=2),
    encoding="utf-8")
print(f"baseline: {base['status']}  violations={len(base_rows)}")

for strategy in ("blocks", "analytic"):
    rep = place_job({"board": board, "parts": parts, "strategy": strategy})
    new_rows = [v for v in rep["violations"] if (v["rule"], v["a"], v["b"]) not in base_keys]
    (OUT / f"eda_place_{strategy}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    s = rep["summary"]
    print(f"\n[{strategy}] moved={s['parts_moved']} fixed={s['parts_fixed']} "
          f"hpwl {s['hpwl_before']}->{s['hpwl_after']} "
          f"drc={s['drc_status']} violations={s['violations']} new={len(new_rows)} sec={s['seconds']}")
    print("moves:", json.dumps(rep["moves"], ensure_ascii=False))
    print("new violations:", json.dumps(new_rows, ensure_ascii=False))
