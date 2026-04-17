from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


def _scan_meta_with_rules(base: Path, recursive: bool) -> list[Path]:
    it = base.rglob("xgb_*_meta.json") if recursive else base.glob("xgb_*_meta.json")
    out: list[Path] = []
    for p in it:
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "\"rules_" in txt:
            out.append(p.resolve())
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    models = root / "models"
    qdir = models / f"_xgb_dirty_quarantine_{time.strftime('%Y%m%d_%H%M%S')}"
    qdir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[Path]] = {
        "models/active": [],
        "models/active_*": [],
        "models/parallel": [],
        "models/cascade": [],
        "models/": [],
    }
    if (models / "active").exists():
        groups["models/active"] = _scan_meta_with_rules(models / "active", recursive=True)
    for d in sorted(models.glob("active_*")):
        if d.is_dir():
            groups["models/active_*"].extend(_scan_meta_with_rules(d, recursive=True))
    if (models / "parallel").exists():
        groups["models/parallel"] = _scan_meta_with_rules(models / "parallel", recursive=True)
    if (models / "cascade").exists():
        groups["models/cascade"] = _scan_meta_with_rules(models / "cascade", recursive=True)
    groups["models/"] = _scan_meta_with_rules(models, recursive=False)

    moved: list[str] = []
    for _, metas in groups.items():
        for meta in metas:
            rel = meta.relative_to(models)
            qmeta = qdir / rel
            qmeta.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(meta), str(qmeta))
            moved.append(str(rel).replace("\\", "/"))

            pkl = meta.with_name(meta.name.replace("_meta.json", ".pkl"))
            if pkl.exists():
                rel_pkl = pkl.resolve().relative_to(models)
                qpkl = qdir / rel_pkl
                qpkl.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(pkl), str(qpkl))
                moved.append(str(rel_pkl).replace("\\", "/"))

    summary = {
        "quarantine_root": str(qdir.resolve()),
        "dirty_counts": {
            "active": len(groups["models/active"]),
            "active_star": len(groups["models/active_*"]),
            "parallel": len(groups["models/parallel"]),
            "cascade": len(groups["models/cascade"]),
            "models_root": len(groups["models/"]),
        },
        "dirty_files": {k: [str(p) for p in v] for k, v in groups.items()},
        "moved_count": len(moved),
        "moved_files": moved,
    }
    out = root / "data" / "xgb_dirty_quarantine_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"summary": str(out), "dirty_counts": summary["dirty_counts"], "moved_count": len(moved)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
