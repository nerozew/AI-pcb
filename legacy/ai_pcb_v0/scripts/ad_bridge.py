"""P0 最小 Altium 桥接：发 request.json，启动 AD26 DelphiScript，读 response.json。

只用于 P0 验证。正式产品会把它包在 adapters.AdBridge 后面。
不修改任何工程文件；写操作由调用方显式发起。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path("C:/Users/Public/altium_mcp")
MCP = Path(__file__).resolve().parents[1] / "third_party" / "altium-mcp"
sys.path.insert(0, str(MCP / "server"))
import script_bundle  # noqa: E402

ALTIUM = Path(os.environ.get("ALTIUM_EXE", r"D:\Altium\AD26\X2.EXE"))
PROJECT = MCP / "server" / "AltiumScript" / "Altium_API.PrjScr"


def run(command: str, params: dict, timeout: float = 120) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    req, resp = ROOT / "request.json", ROOT / "response.json"
    if req.exists():
        return {"success": False, "error": "request.json 已存在，可能有另一个命令在跑"}

    request_id = uuid.uuid4().hex[:12]
    payload = {"command": command, "request_id": request_id, **params}
    # 脚本按行解析 JSON，必须缩进；ASCII 内容避免编码差异
    req.write_text(json.dumps(payload, indent=2), encoding="ascii")
    try:
        if resp.exists():
            resp.unlink()
        bundle = script_bundle.ensure_bundle(PROJECT, ROOT / "bridge")
        cmd = f'"{ALTIUM}" -RScriptingSystem:RunScriptFile(FileName={bundle}^|ProcName=Run)'
        subprocess.Popen(cmd, shell=True)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if resp.exists():
                try:
                    data = json.loads(resp.read_text(encoding="utf-8", errors="replace"), strict=False)
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.25)
                    continue
                if data.get("request_id") in (None, request_id):
                    return data
            time.sleep(0.25)
        return {"success": False, "error": f"超时 {timeout}s，未收到 response.json"}
    finally:
        try:
            if req.exists():
                req.unlink()
        except OSError:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description="P0 Altium 桥接")
    ap.add_argument("command")
    ap.add_argument("--params", default="{}", help="JSON 参数")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    result = run(args.command, json.loads(args.params), args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
