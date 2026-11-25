"""从 RAGFlow 检索规则相关段落，保存为 JSON，供规则 Agent 生成 draft。

只读；不写 RAGFlow，不写数据库。
用法：
  python scripts/fetch_ragflow.py "TPS561208 layout guidelines input capacitor VIN"
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"D:\Code_all\AI-pcb")
OUT = ROOT / "work" / "runs" / "ragflow"


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"缺少环境变量 {name}；先复制 .env.example 为 .env 并填写")
    return value


def main() -> None:
    load_env()
    base = need("RAGFLOW_API_URL").rstrip("/")
    key = need("RAGFLOW_API_KEY")
    dataset_ids = [x.strip() for x in need("RAGFLOW_DATASET_IDS").split(",") if x.strip()]
    question = " ".join(sys.argv[1:]) or "TPS561208 layout guidelines input capacitor VIN"

    payload = {
        "question": question,
        "dataset_ids": dataset_ids,
        "page": 1,
        "page_size": 20,
        "top_k": 20,
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "keyword": False,
        "highlight": False,
    }
    url = base + os.environ.get("RAGFLOW_RETRIEVAL_PATH", "/api/v1/retrieval")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"RAGFlow HTTP {e.code}: {body}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "retrieved.json").write_text(
        json.dumps({"question": question, "response": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    chunks = (data.get("data") or {}).get("chunks") or []
    print(f"question: {question}")
    print(f"chunks: {len(chunks)} -> {OUT / 'retrieved.json'}")
    for c in chunks[:10]:
        snippet = (c.get("content") or "").replace("\n", " ")[:180]
        print(f"- doc={c.get('document_id')} page={c.get('page')} score={c.get('similarity')} | {snippet}")


if __name__ == "__main__":
    main()
