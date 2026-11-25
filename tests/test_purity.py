"""依赖红线：AST 扫描，不执行模块。"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "ai_pcb"

FORBIDDEN = {
    "domain": {"pydantic", "fastapi", "eda_agent", "shapely"},
    "geometry": {"eda_agent", "fastapi"},
    "rules": {"eda_agent", "fastapi", "shapely"},
    "checks": {"eda_agent", "fastapi"},
    "knowledge": {"eda_agent", "fastapi"},
    "web": {"eda_agent"},
}


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_forbidden_imports():
    problems = []
    for area, forbidden in FORBIDDEN.items():
        folder = ROOT / area
        if not folder.exists():
            continue
        for path in folder.rglob("*.py"):
            bad = imports(path) & forbidden
            if bad:
                problems.append(f"{path.relative_to(ROOT)} imports {sorted(bad)}")
    assert not problems, "\n".join(problems)


def test_only_adapter_imports_eda_agent():
    if not ROOT.exists():
        return
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("adapters", "eda_agent"):
            continue
        if "eda_agent" in imports(path):
            raise AssertionError(f"{rel} imports eda_agent; only adapters/eda_agent may")
