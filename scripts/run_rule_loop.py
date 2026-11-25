"""规则驱动的布局循环 + 局部修复（demo）。

读板 → 多组引擎参数 → eda_agent 布局 → 逐条校验 → 选最优
→ 对未达标的软规则做局部微移（保持硬约束）→ 复检。
不写 AD、不保存工程。
"""
import json
import math
import os
from pathlib import Path

LAB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119")
BOARD = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-Collab-20261119\boards\Buck_Unrouted_Source.PcbDoc")
OUT = Path(r"D:\Code_all\AI-pcb\work\runs\p0_buck")
RULES = OUT / "effective_rules.json"

os.environ["EDA_AGENT_WORKSPACE"] = str(LAB / "ipc")

from eda_agent.bridge.altium_bridge import get_bridge  # noqa: E402
from eda_agent.layout.bench import copy_board  # noqa: E402
from eda_agent.layout.drc import verdict  # noqa: E402
from eda_agent.layout.place.job import place_job  # noqa: E402
from eda_agent.layout.place.transform import set_pose  # noqa: E402
from eda_agent.layout.read_altium import read_live_board  # noqa: E402


def vkey(v: dict) -> tuple:
    return (v.get("rule"), v.get("a"), v.get("b"))


def blocked_refs(rows: list[dict]) -> set[str]:
    """从违规对象里提取阻挡器件，如 pad:R2#1 -> R2。"""
    refs = set()
    for v in rows:
        for key in ("a", "b"):
            s = str(v.get(key, ""))
            if s.startswith("pad:") and "#" in s:
                ref = s[4:].split("#", 1)[0].strip()
                if ref:
                    refs.add(ref)
    return refs


def inside(poly: list[tuple[float, float]], x: float, y: float) -> bool:
    if len(poly) < 3:
        return False
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def pad_mm(placed, a: str, b: str, net: str):
    pa = [p for p in placed.pads if p.comp == a and (not net or p.net == net)]
    pb = [p for p in placed.pads if p.comp == b and (not net or p.net == net)]
    if not pa or not pb:
        return None, None, None
    best = min(((p, q) for p in pa for q in pb),
               key=lambda pq: math.hypot(pq[0].x - pq[1].x, pq[0].y - pq[1].y))
    return math.hypot(best[0].x - best[1].x, best[0].y - best[1].y) * 0.0254, best[0], best[1]


def evaluate(placed, moved_refs, parts, soft_rules, base_keys) -> dict:
    v = verdict(placed)
    new_drc = [x.as_dict() for x in v["violations"]
               if vkey(x.as_dict()) not in base_keys]
    anchors_moved = sorted(set(moved_refs) - set(parts))
    side_ok = all(placed.component(r) is not None and placed.component(r).side == "top"
                  for r in moved_refs)
    inside_ok = all(inside(placed.outline, c.x, c.y) for c in placed.components)
    soft = []
    for rule in soft_rules:
        t = rule["targets"]
        d_mm, _, _ = pad_mm(placed, t["a"], t["b"], t.get("net", ""))
        if d_mm is None:
            soft.append({"rule_id": rule["rule_id"], "status": "not_evaluated"})
            continue
        limit = rule["params"]["max_distance_mm"]
        soft.append({"rule_id": rule["rule_id"],
                     "status": "pass" if d_mm <= limit else "fail",
                     "value_mm": round(d_mm, 2), "limit_mm": limit})
    return {
        "hard_ok": not new_drc and not anchors_moved and side_ok and inside_ok,
        "new_drc": len(new_drc),
        "new_drc_rows": new_drc,
        "anchors_moved": anchors_moved,
        "side_ok": side_ok,
        "inside_ok": inside_ok,
        "soft_pass": sum(1 for s in soft if s["status"] == "pass"),
        "soft_total": len(soft),
        "soft": soft,
    }


def repair(placed, moved_refs, parts, soft_rules, base_keys, max_steps: int = 30):
    """对未达标软规则做贪心微移 + 旋转；记录被硬约束挡住的原因。"""
    improved, blocked = [], []
    for _ in range(max_steps):
        changed = False
        current = evaluate(placed, moved_refs, parts, soft_rules, base_keys)
        for rule, result in zip(soft_rules, current["soft"]):
            if result["status"] != "fail":
                continue
            a = rule["targets"]["a"]
            comp = placed.component(a)
            if comp is None:
                continue
            _, pa, pb = pad_mm(placed, a, rule["targets"]["b"], rule["targets"].get("net", ""))
            if pa is None or pb is None:
                continue
            dx, dy = pb.x - pa.x, pb.y - pa.y
            length = math.hypot(dx, dy) or 1.0
            ux, uy = dx / length, dy / length
            trials = []
            for rot in (0, 90, 180, 270):
                for step in (0.5, 1.0, 2.0):
                    for ang in range(0, 360, 45):
                        th = math.radians(ang)
                        trials.append((rot, math.cos(th) * step, math.sin(th) * step))
                    trials.append((rot, ux * step, uy * step))
            best = None
            best_d = result["value_mm"]
            blocked_rows = []
            for rot, ddx, ddy in trials:
                trial = copy_board(placed)
                set_pose(trial, a, x=comp.x + ddx, y=comp.y + ddy,
                         rotation=(comp.rotation + rot) % 360.0)
                ev = evaluate(trial, set(moved_refs) | {a}, parts, soft_rules, base_keys)
                match = next((s for s in ev["soft"] if s["rule_id"] == rule["rule_id"]), None)
                if match is None or "value_mm" not in match:
                    continue
                d_mm = match["value_mm"]
                if ev["hard_ok"]:
                    if d_mm < best_d:
                        best_d, best = d_mm, trial
                elif d_mm < best_d:
                    blocked_rows.extend(ev.get("new_drc_rows", [])[:2])
            if best is not None:
                placed = best
                moved_refs = set(moved_refs) | {a}
                improved.append({"rule_id": rule["rule_id"], "value_mm": best_d})
                changed = True
            else:
                # 定向移开阻挡件：只移真正挡住 a 的器件，移完再把 a 拉近；
                # 只有最终距离确实变小才接受。
                candidates = blocked_refs(blocked_rows) & set(parts) - {a}
                best_block = None
                best_block_d = result["value_mm"]
                for k in candidates:
                    ck = placed.component(k)
                    ca = placed.component(a)
                    if ck is None or ca is None:
                        continue
                    vx, vy = ck.x - ca.x, ck.y - ca.y
                    length = math.hypot(vx, vy) or 1.0
                    ux, uy = vx / length, vy / length
                    for step in (1.0, 2.0):
                        for ang in (-30, 0, 30):
                            th = math.radians(ang)
                            dx = (ux * math.cos(th) - uy * math.sin(th)) * step
                            dy = (ux * math.sin(th) + uy * math.cos(th)) * step
                            trial_k = copy_board(placed)
                            set_pose(trial_k, k, x=ck.x + dx, y=ck.y + dy, rotation=ck.rotation)
                            ev_k = evaluate(trial_k, set(moved_refs) | {k},
                                            parts, soft_rules, base_keys)
                            if not ev_k["hard_ok"] or ev_k["soft_pass"] < current["soft_pass"]:
                                continue
                            ca2 = trial_k.component(a)
                            _, pa2, pb2 = pad_mm(trial_k, a, rule["targets"]["b"],
                                                 rule["targets"].get("net", ""))
                            if ca2 is None or pa2 is None or pb2 is None:
                                continue
                            ax, ay = pb2.x - pa2.x, pb2.y - pa2.y
                            alen = math.hypot(ax, ay) or 1.0
                            uax, uay = ax / alen, ay / alen
                            for astep in (0.5, 1.0):
                                for arot in (0, 90, 180, 270):
                                    trial_a = copy_board(trial_k)
                                    set_pose(trial_a, a,
                                             x=ca2.x + uax * astep,
                                             y=ca2.y + uay * astep,
                                             rotation=(ca2.rotation + arot) % 360.0)
                                    ev_a = evaluate(trial_a, set(moved_refs) | {k, a},
                                                    parts, soft_rules, base_keys)
                                    if not ev_a["hard_ok"]:
                                        continue
                                    match = next((s for s in ev_a["soft"]
                                                  if s["rule_id"] == rule["rule_id"]), None)
                                    if match is None or "value_mm" not in match:
                                        continue
                                    if match["value_mm"] < best_block_d:
                                        best_block_d = match["value_mm"]
                                        best_block = (trial_a, k)
                if best_block is not None:
                    placed, k = best_block
                    moved_refs = set(moved_refs) | {k, a}
                    improved.append({"rule_id": f"blocker:{k}",
                                     "value_mm": best_block_d})
                    changed = True
                    break
                blocked_rows = list({vkey(v): v for v in blocked_rows}.values())
                blocked.append({"rule_id": rule["rule_id"],
                                "from_mm": result["value_mm"],
                                "blocked_by": blocked_rows[:6]})
        if not changed:
            break
    blocked = list({b["rule_id"]: b for b in blocked}.values())
    return placed, moved_refs, improved, blocked


def moves_from(orig, placed) -> list[dict]:
    out = []
    for c in placed.components:
        old = orig.component(c.ref)
        if old and (abs(old.x - c.x) > 1e-6 or abs(old.y - c.y) > 1e-6
                    or abs((old.rotation - c.rotation) % 360.0) > 1e-6):
            out.append({"designator": c.ref, "x": round(c.x), "y": round(c.y),
                        "rotation": round(c.rotation, 3)})
    return out


def main() -> None:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    parts = rules["parts"]
    soft_rules = [r for r in rules["soft_rules"] if r["kind"] == "pad_distance"]

    bridge = get_bridge()
    bridge.send_command("application.set_active_document", {"file_path": str(BOARD)})
    board = read_live_board(str(BOARD))
    print(f"board: {board.name} components={len(board.components)} parts={len(parts)} "
          f"soft_rules={len(soft_rules)}")

    base = verdict(board)
    base_keys = {vkey(v.as_dict()) for v in base["violations"]}
    print(f"baseline: {base['status']} violations={len(base_keys)}")

    configs = [{"strategy": s, "decap_pull": d, "grid_mm": 0.5}
               for s in ("blocks", "analytic") for d in (0.0, 1.0)]

    results = []
    for cfg in configs:
        rep = place_job({"board": board, "parts": parts, "strategy": cfg["strategy"],
                         "decap_pull": cfg["decap_pull"], "grid_mm": cfg["grid_mm"]})
        placed = copy_board(board)
        for m in rep["moves"]:
            set_pose(placed, m["designator"], x=m["x"], y=m["y"], rotation=m["rotation"])
        moved = {m["designator"] for m in rep["moves"]}
        ev = evaluate(placed, moved, parts, soft_rules, base_keys)
        ev["failed"] = rep["summary"]["failed"]
        if ev["failed"]:
            ev["hard_ok"] = False
        rec = {"config": cfg, "hpwl_after": rep["summary"]["hpwl_after"],
               "seconds": rep["summary"]["seconds"], **ev, "placed": placed}
        results.append(rec)
        print(f"[{cfg['strategy']:8s} decap={cfg['decap_pull']:.1f}] "
              f"hard={'OK' if ev['hard_ok'] else 'FAIL'} new_drc={ev['new_drc']} "
              f"anchors_moved={ev['anchors_moved']} side={ev['side_ok']} "
              f"inside={ev['inside_ok']} soft={ev['soft_pass']}/{ev['soft_total']} "
              f"hpwl={rec['hpwl_after']}")

    best = sorted(results, key=lambda r: (not r["hard_ok"], -r["soft_pass"],
                                          r["hpwl_after"]))[0]
    print(f"\nBEST before repair: {json.dumps(best['config'])} "
          f"hard={best['hard_ok']} soft={best['soft_pass']}/{best['soft_total']}")

    if best["hard_ok"] and best["soft_pass"] < best["soft_total"]:
        moved = {m["designator"] for m in []}  # recompute from placed vs board below
        moved = {c.ref for c in best["placed"].components
                 if board.component(c.ref) and (
                     abs(board.component(c.ref).x - c.x) > 1e-6
                     or abs(board.component(c.ref).y - c.y) > 1e-6
                     or abs((board.component(c.ref).rotation - c.rotation) % 360) > 1e-6)}
        placed, moved, improved, blocked = repair(best["placed"], moved, parts, soft_rules, base_keys)
        ev = evaluate(placed, moved, parts, soft_rules, base_keys)
        best = {**best, **ev, "placed": placed,
                "hpwl_after": best["hpwl_after"], "repaired": improved,
                "blocked": blocked}
        print(f"AFTER repair: hard={ev['hard_ok']} soft={ev['soft_pass']}/{ev['soft_total']} "
              f"improved_steps={len(improved)}")
        print("  last:", json.dumps(improved[-4:], ensure_ascii=False))
        for s in ev["soft"]:
            print(" ", s)
        if blocked:
            print("blocked:", json.dumps(blocked, ensure_ascii=False)[:800])

    best_out = {k: v for k, v in best.items() if k != "placed"}
    best_out["moves"] = moves_from(board, best["placed"])
    report = {"board": board.name, "rules": str(RULES),
              "candidates": [{k: v for k, v in r.items() if k != "placed"} for r in results],
              "best": best_out}
    (OUT / "rule_loop_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nFINAL:", json.dumps(best_out["config"]), "hard_ok=", best_out["hard_ok"],
          "soft=", f"{best_out['soft_pass']}/{best_out['soft_total']}")
    print("moves:", json.dumps(best_out["moves"], ensure_ascii=False))


if __name__ == "__main__":
    main()
