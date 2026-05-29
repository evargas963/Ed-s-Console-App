"""Pre-commit: run encoder/model/feature test cone when sequence-encoder paths change.

Closes the loop on stale-test misses after encoder width/schema changes (afac60b class):
agents cannot claim green from a hand-picked pytest slice while leaving cone tests red.

Authoritative rule: AGENTS.md § Encoder cone (mandatory pytest cone).
Paired: tests/test_check_fix_everything_we_touch.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Production + contract paths that change LSTM/Transformer vector width or schema guards.
ENCODER_PRODUCER_PATHS: frozenset[str] = frozenset(
    {
        "lstm_data.py",
        "lstm_model.py",
        "features/lstm_sequence_input.py",
        "ml_predict.py",
        "transformer_train.py",
        "feature_contracts.py",
    }
)

# Test globs under tests/ — kept in sync with AGENTS.md § Encoder cone list.
ENCODER_CONE_TEST_GLOBS: tuple[str, ...] = (
    "test_lstm*.py",
    "test_transformer*.py",
    "test_ml_feature*.py",
    "test_ml_predict*.py",
    "test_feature_contract*.py",
    "test_fusion_model_input*.py",
    "test_db_feature_adapter_layer5*.py",
    "test_training_canonical_input.py",
    "test_model_contract_enforcement.py",
    "test_multi_horizon_ml_bundle*.py",
)

ENCODER_CONE_CITE_MARKERS: tuple[str, ...] = (
    "encoder-cone",
    "encoder cone",
    "check_encoder_cone_tests",
    "ENCODER_CONE",
)

FALSE_GREEN_PASS = re.compile(
    r"\b(?:"
    r"\d+\s*/\s*\d+\s+passed|\d+\s+passed|all\s+tests?\s+pass|tests?\s+green|suite\s+green"
    r")\b",
    re.IGNORECASE,
)


def _norm_staged_path(rel: str) -> str:
    return rel.replace("\\", "/")


def staged_touches_encoder_cone(staged: set[str]) -> bool:
    for rel in staged:
        p = _norm_staged_path(rel)
        if p in ENCODER_PRODUCER_PATHS:
            return True
        if p.startswith("tests/"):
            name = Path(p).name
            for glob in ENCODER_CONE_TEST_GLOBS:
                if Path(name).match(glob):
                    return True
    return False


def collect_encoder_cone_test_paths(repo_root: Path | None = None) -> list[str]:
    root = repo_root or REPO_ROOT
    tests_dir = root / "tests"
    found: set[str] = set()
    for pattern in ENCODER_CONE_TEST_GLOBS:
        for path in sorted(tests_dir.glob(pattern)):
            found.add(path.relative_to(root).as_posix())
    return sorted(found)


def run_encoder_cone_pytest(repo_root: Path | None = None) -> tuple[int, str]:
    root = repo_root or REPO_ROOT
    targets = collect_encoder_cone_test_paths(root)
    if not targets:
        return 1, "encoder cone: no test files matched ENCODER_CONE_TEST_GLOBS"
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", "--tb=line"]
    proc = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def check_encoder_cone_tests(staged: set[str], repo_root: Path | None = None) -> list[str]:
    """Run encoder cone pytest when staged paths touch encoder producers or cone tests."""
    if not staged_touches_encoder_cone(staged):
        return []
    root = repo_root or REPO_ROOT
    code, output = run_encoder_cone_pytest(root)
    if code == 0:
        return []
    n_files = len(collect_encoder_cone_test_paths(root))
    tail = output[-4000:] if len(output) > 4000 else output
    return [
        "encoder cone pytest failed (AGENTS § Encoder cone — mandatory pytest cone). "
        f"Ran {n_files} test file(s) under tests/ matching ENCODER_CONE_TEST_GLOBS. "
        f"Fix failures or run: python -m pytest {' '.join(collect_encoder_cone_test_paths(root)[:3])} ... -q\n"
        f"{tail}"
    ]


def check_encoder_cone_commit_claim(commit_text: str, staged: set[str]) -> list[str]:
    """Block commit messages that claim pass/green on encoder work without citing the cone."""
    if not staged_touches_encoder_cone(staged):
        return []
    if not FALSE_GREEN_PASS.search(commit_text):
        return []
    lowered = commit_text.lower()
    if any(marker.lower() in lowered for marker in ENCODER_CONE_CITE_MARKERS):
        return []
    if any(p in lowered for p in ("tests/test_lstm", "tests/test_transformer", "tests/test_ml_feature")):
        return []
    return [
        "commit message: claims tests passed/green while encoder paths are staged, "
        "but does not cite encoder-cone pytest (AGENTS § Encoder cone). "
        "Include 'encoder-cone' or list tests/test_lstm* … test_feature_contract* files run."
    ]


def main() -> int:
    code, output = run_encoder_cone_pytest()
    if output:
        print(output)
    return code


def check_encoder_cone_documentation(repo_root: Path | None = None) -> list[str]:
    """AGENTS must document the cone rule and list globs."""
    root = repo_root or REPO_ROOT
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return ["AGENTS.md: missing (Encoder cone section)"]
    text = agents.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    if "Encoder cone" not in text or "ENCODER_CONE_TEST_GLOBS" not in text:
        errors.append("AGENTS.md: missing § Encoder cone (mandatory pytest cone)")
    if "check_encoder_cone_tests" not in text:
        errors.append("AGENTS.md: Encoder cone missing check_encoder_cone_tests registry cite")
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
