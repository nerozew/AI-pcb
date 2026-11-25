"""用已安装的 eda_agent 对 wisp6 65 器件做只读整板布局尝试。

不写 AD、不保存工程；聚焦已打开的 wisp-6.PcbDoc，读板，跑 blocks / analytic，
把结果写到 work/runs/p0_wisp6_eda。
"""
import json
import os
from pathlib import Path

LAB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119")
BOARD = Path(r"D:\Code_all\AI-pcb\third_party\wisp6-hardware\Basic Node\wisp-6.PcbDoc")
OUT = Path(r"D:\Code_all\AI-pcb\work\runs\p0_wisp6_eda")

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

base = verdict(board)
base_rows = [v.as_dict() for v in base["violations"]]
base_keys = {(v["rule"], v["a"], v["b"]) for v in base_rows}
(OUT / "baseline.json").write_text(
    json.dumps({"status": base["status"], "violations": base_rows}, ensure_ascii=False, indent=2),
    encoding="utf-8")
print(f"baseline: {base['status']}  violations={len(base_rows)}")

# parts 不给，让 placer 用位号/锁定规则自己固定连接器、测试点等
for strategy in ("blocks", "analytic"):
    rep = place_job({"board": board, "strategy": strategy})
    new_rows = [v for v in rep["violations"] if (v["rule"], v["a"], v["b"]) not in base_keys]
    (OUT / f"eda_place_{strategy}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    s = rep["summary"]
    print(f"\n[{strategy}] moved={s['parts_moved']} fixed={s['parts_fixed']} "
          f"hpwl {s['hpwl_before']}->{s['hpwl_after']} "
          f"drc={s['drc_status']} violations={s['violations']} new={len(new_rows)} sec={s['seconds']}")
    print("failed:", s["failed"])
    print("moves:", json.dumps(rep["moves"], ensure_ascii=False)[:2000])
    print("new violations:", json.dumps(new_rows[:10], ensure_ascii=False))
