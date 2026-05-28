"""Rollback CLI — move corpus bundles between corpora/ and archive/.

Rollback is filesystem-based: every "trained bundle" lives at
`core/data/corpora/<layer>/<bundle_id>/`. Removing that directory undoes its
entire contribution to canon / plot / rules / DPO retrieval.

Crucially, **nothing is permanently deleted**: --remove and --to original move
bundles into `core/data/archive/<layer>/<bundle_id>_<ts>/`. The user can
--restore them later if they regret rolling back.

Commands:
  python scripts/rollback.py --list
      Show all corpora + archived bundles, with summary stats.

  python scripts/rollback.py --to original
      Archive every `user/*` bundle, leaving only the original baseline.

  python scripts/rollback.py --remove <corpus_id>
      Archive one specific bundle (e.g. "user/20260528_x7k2").

  python scripts/rollback.py --restore <archive_id>
      Move an archived bundle back to corpora/ (un-rollback).

  python scripts/rollback.py --wipe-all  [--yes]
      DELETE all of core/data/. Last-resort reset. Confirmation required.

After any structural change you should restart the backend so its caches /
active corpus pointer are consistent:
      python scripts/stop_services.py --backend
      python scripts/start_services.py --backend
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


_CORE_DIR = Path(__file__).resolve().parent.parent / "core"
DATA_DIR = _CORE_DIR / "data"
CORPORA_DIR = DATA_DIR / "corpora"
ARCHIVE_DIR = DATA_DIR / "archive"


def _list_corpora() -> list[str]:
    if not CORPORA_DIR.exists():
        return []
    out = []
    for layer_dir in CORPORA_DIR.iterdir():
        if not layer_dir.is_dir():
            continue
        for b in layer_dir.iterdir():
            if b.is_dir():
                out.append(f"{layer_dir.name}/{b.name}")
    return sorted(out)


def _list_archived() -> list[str]:
    if not ARCHIVE_DIR.exists():
        return []
    out = []
    for layer_dir in ARCHIVE_DIR.iterdir():
        if not layer_dir.is_dir():
            continue
        for b in layer_dir.iterdir():
            if b.is_dir():
                out.append(f"{layer_dir.name}/{b.name}")
    return sorted(out)


def _stats(bundle: Path) -> dict:
    """Cheap summary read straight off disk (no backend needed)."""
    meta_p = bundle / "meta.json"
    canon_p = bundle / "canon.jsonl"
    plot_p = bundle / "plot.jsonl"
    dpo_p = bundle / "dpo.jsonl"
    snap_p = bundle / "snapshot.json"

    meta = {}
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except Exception:
            pass

    def _lines(p: Path) -> int:
        if not p.exists():
            return 0
        try:
            return sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            return 0

    chunks = 0
    if snap_p.exists():
        try:
            chunks = int(json.loads(snap_p.read_text(encoding="utf-8")).get("chunks_processed", 0))
        except Exception:
            pass

    return {
        "created_at": meta.get("created_at", ""),
        "source": meta.get("source_path", ""),
        "chunks": chunks,
        "dpo": _lines(dpo_p),
        "canon": _lines(canon_p),
        "plot": _lines(plot_p),
    }


def _print_table(rows: list[tuple[str, dict]], header: str) -> None:
    if not rows:
        print(f"{header}: (none)")
        return
    print(f"{header}:")
    print(f"  {'CORPUS_ID':<48} {'CHUNKS':>7} {'DPO':>5} {'CANON':>5} {'PLOT':>5}  CREATED")
    for cid, s in rows:
        created = s.get("created_at", "")[:19]
        print(f"  {cid:<48} {s['chunks']:>7} {s['dpo']:>5} {s['canon']:>5} {s['plot']:>5}  {created}")


def cmd_list() -> int:
    active_rows = [(cid, _stats(CORPORA_DIR / cid)) for cid in _list_corpora()]
    archived_rows = [(cid, _stats(ARCHIVE_DIR / cid)) for cid in _list_archived()]
    _print_table(active_rows, "Active corpora")
    print()
    _print_table(archived_rows, "Archived")
    return 0


def _archive_bundle(corpus_id: str) -> Path:
    src = CORPORA_DIR / corpus_id
    if not src.exists():
        raise SystemExit(f"[rollback] not found: {src}")
    layer, bundle = corpus_id.split("/", 1)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_dir = ARCHIVE_DIR / layer
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{bundle}_{ts}"
    shutil.move(str(src), str(dest))
    return dest


def cmd_remove(corpus_id: str) -> int:
    dest = _archive_bundle(corpus_id)
    print(f"[rollback] archived: {corpus_id}  →  archive/{dest.parent.name}/{dest.name}")
    print("[rollback] run scripts/stop_services.py + start_services.py for backend caches to refresh.")
    return 0


def cmd_to_original() -> int:
    user_bundles = [cid for cid in _list_corpora() if cid.startswith("user/")]
    if not user_bundles:
        print("[rollback] no user-layer bundles to archive — already at original baseline.")
        return 0
    for cid in user_bundles:
        dest = _archive_bundle(cid)
        print(f"[rollback] archived: {cid}  →  archive/{dest.parent.name}/{dest.name}")
    print(f"[rollback] {len(user_bundles)} user bundle(s) archived. "
          "Restart the backend for caches to refresh.")
    return 0


def cmd_restore(archive_id: str) -> int:
    src = ARCHIVE_DIR / archive_id
    if not src.exists():
        raise SystemExit(f"[rollback] archive not found: {src}")
    layer, bundle_ts = archive_id.split("/", 1)
    # strip trailing _YYYYMMDD_HHMMSS to recover original bundle name
    parts = bundle_ts.rsplit("_", 2)
    if len(parts) >= 3 and len(parts[-1]) == 6 and len(parts[-2]) == 8:
        bundle = "_".join(parts[:-2])
    else:
        bundle = bundle_ts  # fall back to whole name
    dest = CORPORA_DIR / layer / bundle
    if dest.exists():
        raise SystemExit(f"[rollback] cannot restore — destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    print(f"[rollback] restored: archive/{archive_id}  →  corpora/{layer}/{bundle}")
    print("[rollback] restart the backend.")
    return 0


def cmd_wipe_all(confirm: bool) -> int:
    if not DATA_DIR.exists():
        print("[rollback] core/data/ already absent.")
        return 0
    if not confirm:
        print("[rollback] --wipe-all is destructive (deletes corpora + archive + drafts + logs).")
        print("[rollback] re-run with --yes to confirm. Backend should be stopped first.")
        return 2
    shutil.rmtree(DATA_DIR)
    print(f"[rollback] wiped {DATA_DIR}. Restart the backend after.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="show active + archived corpora")
    g.add_argument("--to", choices=["original"], help='roll back to a layer ("original" only for now)')
    g.add_argument("--remove", metavar="CORPUS_ID", help='archive one bundle, e.g. "user/20260528_x7k2"')
    g.add_argument("--restore", metavar="ARCHIVE_ID", help='restore an archived bundle, e.g. "user/20260528_x7k2_20260530_120000"')
    g.add_argument("--wipe-all", action="store_true", help="DELETE all of core/data/ — last resort")
    ap.add_argument("--yes", action="store_true", help="confirm destructive operations")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.to == "original":
        return cmd_to_original()
    if args.remove:
        return cmd_remove(args.remove)
    if args.restore:
        return cmd_restore(args.restore)
    if args.wipe_all:
        return cmd_wipe_all(args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
