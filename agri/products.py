"""Verified product catalogue + recommendation engine.

A product can be recommended for (crop, problem) ONLY if an agronomist-verified row in
product_targets says so, with the source quote. Dosage text is shown exactly as stored."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import db
from .taxonomy import crops, problems

REQUIRED = ["product_name", "category", "crop", "problem", "dosage", "method", "source_doc", "source_ref",
            "source_quote", "verified_by", "verified_on"]


class ProductFileError(ValueError):
    pass


def load_products_csv(path: str) -> dict:
    """Load data/products/verified_products.csv. Rejects rows that are unverified, unsourced,
    or point at a crop/problem that is not in the taxonomy."""
    rows = list(csv.DictReader(Path(path).open(encoding="utf-8-sig")))
    errors, loaded = [], 0
    for n, r in enumerate(rows, start=2):
        missing = [c for c in REQUIRED if not (r.get(c) or "").strip()]
        if missing:
            errors.append(f"line {n}: missing {missing}")
            continue
        crop, prob = r["crop"].strip().lower(), r["problem"].strip().lower()
        if crop not in crops():
            errors.append(f"line {n}: unknown crop '{crop}'")
            continue
        if prob != "general_crop_health" and prob not in problems(crop):
            errors.append(f"line {n}: problem '{prob}' is not listed for {crop} in taxonomy.yaml")
            continue
        try:
            vdate = date.fromisoformat(r["verified_on"].strip())
        except ValueError:
            errors.append(f"line {n}: verified_on must be YYYY-MM-DD")
            continue
        p = db.fetchone(
            "INSERT INTO products (name, aliases, category, composition, compatibility, precautions, status, verified_by, verified_on) "
            "VALUES (%s,%s,%s,%s,%s,%s,'verified',%s,%s) ON CONFLICT (name) DO UPDATE SET "
            "aliases=EXCLUDED.aliases, category=EXCLUDED.category, composition=EXCLUDED.composition, "
            "compatibility=EXCLUDED.compatibility, precautions=EXCLUDED.precautions, verified_by=EXCLUDED.verified_by, "
            "verified_on=EXCLUDED.verified_on, status='verified' RETURNING id",
            (r["product_name"].strip(), [a.strip() for a in (r.get("aliases") or "").split(";") if a.strip()],
             r["category"].strip(), r.get("composition", "").strip(), r.get("compatibility", "").strip(),
             r.get("precautions", "").strip(), r["verified_by"].strip(), vdate))
        db.execute(
            "INSERT INTO product_targets (product_id, crop, problem, growth_stage, method, dosage, frequency, source_doc, source_ref, source_quote) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (product_id, crop, problem, method) DO UPDATE SET "
            "growth_stage=EXCLUDED.growth_stage, dosage=EXCLUDED.dosage, frequency=EXCLUDED.frequency, "
            "source_doc=EXCLUDED.source_doc, source_ref=EXCLUDED.source_ref, source_quote=EXCLUDED.source_quote",
            (p["id"], crop, prob, r.get("growth_stage", "").strip() or None, r["method"].strip(), r["dosage"].strip(),
             r.get("frequency", "").strip(), r["source_doc"].strip(), r["source_ref"].strip(), r["source_quote"].strip()))
        loaded += 1
    return {"loaded": loaded, "errors": errors}


@dataclass
class ProductMatch:
    name: str
    category: str
    problem: str
    method: str
    dosage: str
    frequency: str
    growth_stage: str | None
    precautions: str
    compatibility: str
    source_doc: str
    source_ref: str
    exact: bool  # matched the diagnosed problem (True) or general crop health (False)


def recommend(crop: str, problem_keys: list[str], include_general: bool = True) -> list[ProductMatch]:
    """Deterministic: verified rows for this crop and these problems. Exact matches first."""
    if not crop:
        return []
    wanted = list(problem_keys) + (["general_crop_health"] if include_general else [])
    if not wanted:
        return []
    rows = db.fetchall(
        "SELECT p.name, p.category, p.precautions, p.compatibility, t.problem, t.method, t.dosage, t.frequency, "
        "t.growth_stage, t.source_doc, t.source_ref FROM product_targets t JOIN products p ON p.id=t.product_id "
        "WHERE p.status='verified' AND t.crop=%s AND t.problem = ANY(%s)", (crop, wanted))
    order = {k: i for i, k in enumerate(wanted)}
    rows.sort(key=lambda r: order.get(r["problem"], 99))
    return [ProductMatch(r["name"], r["category"] or "", r["problem"], r["method"], r["dosage"], r["frequency"] or "",
                         r["growth_stage"], r["precautions"] or "", r["compatibility"] or "", r["source_doc"],
                         r["source_ref"], r["problem"] != "general_crop_health") for r in rows]


def products_for_crop(crop: str) -> list[ProductMatch]:
    rows = db.fetchall("SELECT DISTINCT problem FROM product_targets WHERE crop=%s", (crop,))
    return recommend(crop, [r["problem"] for r in rows if r["problem"] != "general_crop_health"])


def known_product_names() -> list[str]:
    out = []
    for r in db.fetchall("SELECT name, aliases FROM products WHERE status='verified'"):
        out.append(r["name"])
        out.extend(r["aliases"] or [])
    return out
