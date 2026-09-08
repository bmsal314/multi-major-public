"""Fixtures shared by the rebuilt parser and planner tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))


@pytest.fixture(scope="session")
def synthetic_dir() -> Path:
    """The synthesized DARS fixtures, rendered from source if absent.

    ``.gitignore`` excludes ``*.pdf``, so the PDFs are never committed. They are
    reproduced deterministically from ``tests/fixtures/synthetic_dars.py``, whose
    content comes from the three real 2024-2025 ASU major maps.
    """
    from synthetic_dars import build_all, synthetic_dir as target

    build_all()
    return target()


@pytest.fixture(scope="session")
def real_dir() -> Path:
    folder = ROOT / "tests" / "fixtures" / "dars_real"
    if not folder.is_dir() or not any(folder.glob("*.pdf")):
        pytest.skip("No real DARS exports available in tests/fixtures/dars_real/.")
    return folder


@pytest.fixture(scope="session")
def parsed_synthetic(synthetic_dir: Path) -> dict[str, dict]:
    from backend.pdf_parser import parse_dars_pdf

    return {
        path.stem: parse_dars_pdf(str(path))
        for path in sorted(synthetic_dir.glob("*.pdf"))
    }
