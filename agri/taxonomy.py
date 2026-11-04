"""Loads the agronomist-owned crop/problem taxonomy and glossary."""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import DATA_DIR


@lru_cache
def taxonomy() -> dict:
    return yaml.safe_load((DATA_DIR / "taxonomy.yaml").read_text(encoding="utf-8"))


@lru_cache
def glossary() -> dict:
    return yaml.safe_load((DATA_DIR / "glossary.yaml").read_text(encoding="utf-8"))


def crops() -> dict[str, dict]:
    return taxonomy()["crops"]


def crop_name(crop: str, style: str) -> str:
    c = crops().get(crop)
    if not c:
        return crop
    return c["ta"] if style == "ta" else c["tl"] if style == "ta-Latn" else c["en"]


def problems(crop: str) -> dict[str, dict]:
    """Problems for ONE crop only. There is deliberately no global problem list."""
    return crops().get(crop, {}).get("problems", {})


def problem_name(crop: str, problem: str, style: str) -> str:
    p = problems(crop).get(problem)
    if not p:
        return problem.replace("_", " ")
    return p["ta"] if style == "ta" else p["tl"] if style == "ta-Latn" else p["en"]


def symptom_keys() -> list[str]:
    return list(glossary()["symptom"].keys())
