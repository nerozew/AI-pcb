"""从 Buck 板 + rule_loop_report 生成候选预览 SVG。

只读；用 altium_monkey 离线解析 PcbDoc。固定/移动/被挡用颜色区分。
"""
import argparse
import json
from pathlib import Path

from altium_monkey import AltiumPcbDoc

MM = 0.0254


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    doc = AltiumPcbDoc.from_file(args.pcb)
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    best = report.get("best", {})
    moves = {m["designator"]: m for m in best.get("moves", [])}
    blocked_refs = set()
    for b in best.get("blocked", []):
        for v in b.get("blocked_by", []):
            for key in ("a", "b"):
                s = str(v.get(key, ""))
                if s.startswith("pad:") and "#" in s:
                    blocked_refs.add(s[4:].split("#", 1)[0])

    outline = getattr(doc.board, "outline", None)
    verts = getattr(outline, "vertices", None) or []
    pts = [(v.x_mils * MM, v.y_mils * MM) for v in verts]
    if not pts:
        raise SystemExit("no board outline")

    comps = []
    for idx, c in enumerate(doc.components, start=1):
        ref = c.designator
        if not ref:
            continue
        pads = [p for p in doc.pads if getattr(p, "component_index", -1) == idx]
        xs, ys = [], []
        for p in pads:
            px = getattr(p, "x_mils", None)
            py = getattr(p, "y_mils", None)
            if px is None or py is None:
                continue
            pw = float(getattr(p, "width_mils", 0) or 0)
            ph = float(getattr(p, "top_height", 0) or 0) / 10000.0
            pw = pw if pw > 0 else 10.0
            ph = ph if ph > 0 else 10.0
            xs += [px - pw / 2, px + pw / 2]
            ys += [py - ph / 2, py + ph / 2]
        if xs and (max(xs) - min(xs)) > 0:
            w = (max(xs) - min(xs)) * MM
            h = (max(ys) - min(ys)) * MM
        else:
            w = h = 1.5
        x = c.get_x_mils() * MM
        y = c.get_y_mils() * MM
        rot = c.get_rotation_degrees() or 0
        if ref in moves:
            x = moves[ref]["x"] * MM
            y = moves[ref]["y"] * MM
            rot = moves[ref].get("rotation", rot)
        if int(round(abs(rot))) % 180 == 90:
            w, h = h, w
        comps.append((ref, x, y, w, h, ref in moves, ref in blocked_refs))

    minx = min(p[0] for p in pts)
    maxx = max(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    maxy = max(p[1] for p in pts)
    pad = 5.0
    width = maxx - minx + 2 * pad
    height = maxy - miny + 2 * pad

    def sx(x: float) -> float:
        return x - minx + pad

    def sy(y: float) -> float:
        return height - (y - miny + pad)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" '
        f'font-family="Segoe UI, Arial, sans-serif">',
        f'<rect width="{width:.1f}" height="{height:.1f}" fill="#0d1117"/>',
    ]
    path = " ".join(
        ("M" if i == 0 else "L") + f"{sx(x):.2f},{sy(y):.2f}" for i, (x, y) in enumerate(pts)
    ) + " Z"
    out.append(f'<path d="{path}" fill="none" stroke="#8b949e" stroke-width="0.35"/>')

    for ref, x, y, w, h, moved, blocked in comps:
        color = "#f85149" if blocked else "#3fb950" if moved else "#58a6ff"
        out.append(
            f'<rect x="{sx(x) - w / 2:.2f}" y="{sy(y) - h / 2:.2f}" '
            f'width="{w:.2f}" height="{h:.2f}" fill="{color}" fill-opacity="0.22" '
            f'stroke="{color}" stroke-width="0.25"/>'
        )
        out.append(
            f'<text x="{sx(x):.2f}" y="{sy(y):.2f}" fill="{color}" font-size="2.2" '
            f'text-anchor="middle" dominant-baseline="middle">{ref}</text>'
        )

    out.append(
        f'<text x="{pad:.1f}" y="{height - 2:.1f}" fill="#8b949e" font-size="2">'
        f'蓝=固定  绿=移动  红=被阻挡</text>'
    )
    out.append("</svg>")
    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {args.out}  components={len(comps)}  moved={len(moves)}  blocked={len(blocked_refs)}")


if __name__ == "__main__":
    main()
