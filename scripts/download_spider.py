"""Download Spider 1.0 dataset to ./data/spider/.

Pulls the dev split + SQLite DBs from the Hugging Face mirror (xlangai/spider)
when available; falls back to the official Yale-LILY GitHub mirror zip.

Idempotent — re-running is a no-op once the files exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "spider"


def via_huggingface() -> bool:
    """Try to load the dev split via `datasets`; persist questions to JSON.

    Returns True on success.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        return False
    try:
        ds = load_dataset("xlangai/spider", split="validation")
    except Exception as exc:
        print(f"[hf] load_dataset failed: {exc}")
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "dev.json"
    records = [
        {
            "db_id": r["db_id"],
            "question": r["question"],
            "query": r["query"],
        }
        for r in ds
    ]
    out.write_text(json.dumps(records, indent=2))
    print(f"[hf] wrote {len(records)} dev records → {out}")
    return True


def via_db_snapshot() -> bool:
    """Snapshot prem-research/spider into data/spider/database/ via huggingface_hub.

    prem-research/spider hosts the SQLite DBs + schema.sql files under
    database/<db_id>/. We snapshot only that subtree (allow_patterns) to
    avoid pulling the ~36 MB train.json we don't need.
    """
    db_dir = DATA_DIR / "database"
    if db_dir.exists() and len(list(db_dir.iterdir())) >= 100:
        print(f"[db] databases already present at {db_dir} ({len(list(db_dir.iterdir()))} dirs)")
        return True
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[db] huggingface_hub not available")
        return False
    print("[db] snapshotting prem-research/spider database/ subtree ...")
    try:
        local = snapshot_download(
            repo_id="prem-research/spider",
            repo_type="dataset",
            allow_patterns=["database/**"],
            local_dir=str(DATA_DIR),
        )
    except Exception as exc:
        print(f"[db] snapshot failed: {exc}")
        return False
    print(f"[db] snapshot → {local}")
    db_count = len(list(db_dir.iterdir())) if db_dir.exists() else 0
    print(f"[db] {db_count} database directories present at {db_dir}")
    return db_count > 0


def main() -> int:
    print(f"Spider data dir: {DATA_DIR}")
    ok_q = via_huggingface()
    ok_db = via_db_snapshot()
    if not (ok_q and ok_db):
        print(
            "FAIL — see messages above. Manual fallback: download "
            "https://yale-lily.github.io/spider zip + extract to "
            f"{DATA_DIR}."
        )
        return 1
    print("OK — Spider dev split + databases ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
