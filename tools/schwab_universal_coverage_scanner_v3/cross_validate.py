"""Independent cross-validator — V2 G2 pattern_kind_miss; V3-A vocabulary triggers."""

from __future__ import annotations

from typing import Iterable

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex


def lines_with_vocab_hits(source: str, idx: SchwabCsvIndex) -> set[int]:
    vocab = idx.vocabulary
    out: set[int] = set()
    for i, line in enumerate(source.splitlines(), start=1):
        if vocab.words_in_line(line):
            out.add(i)
    return out


def covered_lines(rows: Iterable[RegisterRow], path: str) -> set[int]:
    """Lines already represented by any scanner row (AST, catch-all, cross-validator)."""
    return {r.line for r in rows if r.path == path}


def cross_validate_python_file(
    rel_path: str,
    source: str,
    existing_rows: list[RegisterRow],
    idx: SchwabCsvIndex,
) -> list[RegisterRow]:
    miss: list[RegisterRow] = []
    token_lines = lines_with_vocab_hits(source, idx)
    cov = covered_lines(existing_rows, rel_path)
    vocab = idx.vocabulary
    for ln in sorted(token_lines):
        if ln in cov:
            continue
        line_text = source.splitlines()[ln - 1][:400]
        toks = vocab.words_in_line(line_text)
        cands = ";".join(idx.candidates_token(toks))
        rid = RegisterRow.make_id(rel_path, ln, 0, "pattern_kind_miss", "cross_validator")
        miss.append(
            RegisterRow(
                register_id=rid,
                language="cross_validator",
                path=rel_path,
                line=ln,
                col=0,
                pattern_kind="pattern_kind_miss",
                surface_form=line_text,
                tokens=" ".join(toks),
                csv_candidates=cands,
                csv_lexical_topk_note=";".join(idx.candidates_embedding_topk(line_text[:512], k=3)),
                v2_trace="V3 G2 cross-validator (CSV vocabulary)",
                notes="independent path vs python AST",
            )
        )
    return miss
