"""Schwab dictionary index + embeddings — V3 G3; vocabulary from CSV (V3-A)."""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

from .paths import ROOT
from .vocabulary import CsvVocabulary, tokenize_for_vocabulary


def tokenize_canonical_field(name: str, min_len: int = 3) -> list[str]:
    return sorted(tokenize_for_vocabulary(name, min_len=min_len))


def _mock_encode(texts: list[str]) -> np.ndarray:
    m = np.zeros((len(texts), 32), dtype=np.float64)
    for i, t in enumerate(texts):
        for ch in t.lower():
            m[i, ord(ch) % 32] += 1.0
    norms = np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    return m / norms


class SchwabCsvIndex:
    def __init__(self, csv_path: Path, *, vocab_min_len: int = 3) -> None:
        self.csv_path = csv_path
        self.by_token: dict[str, list[str]] = defaultdict(list)
        self.rows: list[dict[str, str]] = []
        self._embed_matrix: np.ndarray | None = None
        self._embed_canonical_fields: list[str] | None = None
        self._st_model = None
        self.vocabulary: CsvVocabulary
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.rows.append(row)
        self.vocabulary = CsvVocabulary.from_dictionary_rows(self.rows, min_len=vocab_min_len)
        for row in self.rows:
            cf = (row.get("canonical_field") or "").strip()
            if not cf:
                continue
            seen: set[str] = set()
            for tok in tokenize_canonical_field(cf, min_len=vocab_min_len):
                if tok not in seen:
                    seen.add(tok)
                    self.by_token[tok].append(cf)

    def candidates_token(self, tokens: list[str], *, limit: int = 25) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for t in tokens:
            tl = str(t).lower()
            if len(tl) < 2:
                continue
            for cf in self.by_token.get(tl, ()):
                if cf not in seen:
                    seen.add(cf)
                    out.append(cf)
                    if len(out) >= limit:
                        return out
        return out

    def all_canonical_fields(self) -> list[str]:
        out: list[str] = []
        for r in self.rows:
            cf = (r.get("canonical_field") or "").strip()
            if cf and cf not in out:
                out.append(cf)
        return out

    def _embedding_mode(self) -> str:
        return os.environ.get("SCHWAB_SCANNER_EMBEDDINGS", "minilm").strip().lower()

    def _ensure_embedding_index(self) -> None:
        if self._embed_matrix is not None:
            return
        texts: list[str] = []
        cfs: list[str] = []
        for r in self.rows:
            cf = (r.get("canonical_field") or "").strip()
            if not cf:
                continue
            desc = (r.get("description") or r.get("csv_description") or "").strip()
            cat = (r.get("category") or "").strip()
            likely = (r.get("likely_use") or "").strip()
            blob = f"{cf}. {desc}. {cat}. {likely}".strip()
            texts.append(blob)
            cfs.append(cf)
        if not cfs:
            self._embed_matrix = np.zeros((0, 32), dtype=np.float64)
            self._embed_canonical_fields = []
            return
        mode = self._embedding_mode()
        if mode == "mock":
            mat = _mock_encode(texts)
        else:
            from sentence_transformers import SentenceTransformer

            model_name = os.environ.get(
                "SCHWAB_SCANNER_EMBEDDING_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            )
            if self._st_model is None:
                self._st_model = SentenceTransformer(model_name)
            mat = self._st_model.encode(
                texts,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            mat = mat.astype(np.float64)
            norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
            mat = mat / norms
        self._embed_matrix = mat
        self._embed_canonical_fields = cfs

    def candidates_embedding_topk(self, phrase: str, *, k: int = 3) -> list[str]:
        if not phrase.strip() or not self.rows:
            return []
        self._ensure_embedding_index()
        assert self._embed_matrix is not None and self._embed_canonical_fields is not None
        if self._embed_matrix.shape[0] == 0:
            return []
        mode = self._embedding_mode()
        if mode == "mock":
            q = _mock_encode([phrase.strip()])[0]
        else:
            from sentence_transformers import SentenceTransformer

            model_name = os.environ.get(
                "SCHWAB_SCANNER_EMBEDDING_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            )
            if self._st_model is None:
                self._st_model = SentenceTransformer(model_name)
            q = self._st_model.encode(
                [phrase.strip()],
                convert_to_numpy=True,
                show_progress_bar=False,
            )[0].astype(np.float64)
            q = q / (np.linalg.norm(q) + 1e-9)
        sims = self._embed_matrix @ q
        # Platform-stable ranking (2026-07-03): raw argsort ordered ties by BLAS
        # floating-point noise, which differs across CPU microarchitectures — two CI
        # runner hosts produced byte-different registers for identical input (rows
        # equal, topk note order flipped). Round away kernel noise and break ties
        # lexicographically so the register is byte-identical on every host.
        order = sorted(
            range(len(sims)),
            key=lambda i: (-round(float(sims[i]), 6), self._embed_canonical_fields[i]),
        )[:k]
        return [self._embed_canonical_fields[i] for i in order]


def default_dictionary_path() -> Path:
    return ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
