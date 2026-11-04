"""Crop-specific differential: combines a trained head (when one exists) with symptom evidence
from the farmer's words and the photo. Candidates come ONLY from the detected crop's list."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import get_settings
from .taxonomy import problems


@dataclass
class Candidate:
    problem: str
    score: float
    evidence: list[str]
    calibrated_p: float | None = None  # only set when a trained head produced it


@dataclass
class Triage:
    crop: str
    candidates: list[Candidate] = field(default_factory=list)
    certainty: str = "unclear"  # likely | possible | unclear
    next_question: str | None = None  # leaf_age | photo | None
    healthy: bool = False


def triage(crop: str, symptoms: list[str], leaf_age: str | None, has_photo: bool,
           head_top: list[tuple[str, float]] | None = None, questions_asked: int = 0) -> Triage:
    s = get_settings()
    probs = problems(crop)
    t = Triage(crop=crop)
    sym = set(symptoms)

    head = dict(head_top or [])
    if head_top:
        top_label, top_p = head_top[0]
        if top_label == "healthy" and top_p >= s.disease_likely_conf and not sym:
            t.healthy, t.certainty = True, "likely"
            return t

    for key, p in probs.items():
        psym = set(p.get("symptoms", []))
        overlap = sym & psym
        score = len(overlap) / max(len(psym), 1) if sym else 0.0
        ev = sorted(overlap)
        want_age = p.get("leaf_age")
        if want_age and leaf_age:
            if want_age == leaf_age:
                score += 0.35
                ev.append(f"leaf_age:{leaf_age}")
            else:
                score -= 0.5
        if key in head:
            score += 1.5 * head[key]
        if score > 0:
            t.candidates.append(Candidate(key, round(score, 3), ev, head.get(key)))
    t.candidates.sort(key=lambda c: -c.score)
    t.candidates = t.candidates[:3]

    top = t.candidates[0] if t.candidates else None
    if top and top.calibrated_p is not None and top.calibrated_p >= s.disease_likely_conf:
        t.certainty = "likely"
    elif top and (top.calibrated_p or 0) >= s.disease_min_conf:
        t.certainty = "possible"
    elif top and (len(t.candidates) == 1 or top.score - t.candidates[1].score >= 0.3) and has_photo:
        t.certainty = "possible"
    elif top:
        t.certainty = "possible" if has_photo else "unclear"

    if questions_asked < s.max_questions:
        age_matters = len({probs[c.problem].get("leaf_age") for c in t.candidates} - {None}) > 0
        if leaf_age is None and "yellowing" in sym and age_matters:
            t.next_question = "leaf_age"
        elif not has_photo:
            t.next_question = "photo"
    return t
