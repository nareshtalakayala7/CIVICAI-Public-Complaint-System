"""Explainable, dependency-free NLP triage for the CIVICAI demonstration.

This intentionally uses weighted civic-issue vocabularies instead of a hosted
model. The scoring is deterministic, auditable and works offline; a production
deployment can replace this module with a reviewed multilingual classifier.
"""
from __future__ import annotations

import re
from collections import Counter

CATEGORIES = {
    "Roads & Infrastructure": {
        "category": "Roads & Infrastructure",
        "terms": {"pothole": 4, "road": 2, "street": 1, "sidewalk": 3, "footpath": 3, "bridge": 3, "traffic": 1, "crack": 1, "crossing": 1, "pavement": 1, "రోడ్డు": 3, "రహదారి": 3, "గుంత": 4, "వంతెన": 2},
    },
    "Water Supply": {
        "category": "Water Supply",
        "terms": {"water": 3, "supply": 2, "leak": 2, "pipe": 2, "tap": 1, "sewage": 1, "drinking": 1, "contaminated": 3, "shortage": 2, "hydrant": 2, "నీరు": 3, "నీటి": 3, "సరఫరా": 2, "కలుషిత": 3},
    },
    "Sanitation & Drainage": {
        "category": "Sanitation & Drainage",
        "terms": {"drain": 3, "sewer": 3, "sewage": 3, "overflow": 2, "sanitation": 3, "toilet": 2, "stagnant": 2, "blockage": 2, "flood": 2, "smell": 1, "మురుగు": 3, "డ్రైనేజీ": 3, "కాలువ": 2, "మ్యాన్‌హోల్": 2},
    },
    "Waste Management": {
        "category": "Waste Management",
        "terms": {"garbage": 3, "waste": 3, "rubbish": 3, "trash": 3, "collection": 1, "dump": 2, "dumping": 2, "litter": 2, "recycling": 2, "bin": 1, "చెత్త": 3, "వ్యర్థ": 3, "కుప్ప": 2},
    },
    "Electricity & Lighting": {
        "category": "Electricity & Lighting",
        "terms": {"light": 2, "streetlight": 4, "electricity": 3, "power": 2, "wire": 2, "transformer": 2, "outage": 2, "lamp": 2, "dark": 1, "spark": 3, "విద్యుత్": 3, "కరెంట్": 3, "వీధి దీపం": 4, "దీపం": 2},
    },
    "Environment": {
        "category": "Environment",
        "terms": {"pollution": 3, "noise": 2, "tree": 2, "smoke": 2, "air": 1, "environment": 3, "burning": 2, "dust": 2, "illegal": 1, "construction": 1, "కాలుష్యం": 3, "శబ్దం": 2, "చెట్టు": 2, "పర్యావరణం": 3},
    },
}

CRITICAL = ("electrocution", "electric shock", "live wire", "gas leak", "collapsed", "collapse", "life threatening", "injured", "injury", "open manhole", "flooding homes", "contaminated drinking water")
HIGH = ("urgent", "dangerous", "accident", "accidents", "school", "hospital", "overflowing", "severe", "hazard", "unsafe", "exposed wire", "no water", "blocked drain")
LOW = ("minor", "cosmetic", "information only", "suggestion", "small crack")
CRITICAL_TE = ("విద్యుత్ షాక్", "ప్రాణాపాయం", "ప్రమాదకర విద్యుత్ తీగ", "తీవ్ర గాయం", "కలుషిత తాగునీరు")
HIGH_TE = ("అత్యవసరం", "ప్రమాదం", "పాఠశాల", "ఆసుపత్రి", "ప్రమాదకరం", "నీరు రావడం లేదు")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def analyze_complaint(text: str) -> dict:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    tokens = _tokens(normalized)
    token_counts = Counter(tokens)
    scores = {}
    for department, entry in CATEGORIES.items():
        score = 0
        for term, weight in entry["terms"].items():
            if " " in term or not term.isascii():
                score += weight * normalized.lower().count(term)
            else:
                score += weight * token_counts.get(term, 0)
        scores[department] = score
    department = max(scores, key=scores.get)
    best = scores[department]
    total = sum(scores.values())
    if best == 0:
        department, category, confidence = "Roads & Infrastructure", "Other civic issue", 0.28
    else:
        category, confidence = department, min(0.96, round(0.54 + 0.42 * best / max(total, 1), 2))
    lower = normalized.lower()
    if any(term in lower for term in CRITICAL + CRITICAL_TE):
        priority = "Critical"
    elif any(term in lower for term in HIGH + HIGH_TE):
        priority = "High"
    elif any(term in lower for term in LOW):
        priority = "Low"
    else:
        priority = "Medium"
    summary = normalized.split(".")[0].strip()
    if len(summary) < 24:
        summary = normalized[:180].strip()
    if len(summary) > 180:
        summary = summary[:177].rstrip() + "..."
    return {"category": category, "department": department, "priority": priority, "confidence": confidence,
            "summary": summary or "Civic service request submitted.", "scores": scores,
            "method": "Explainable keyword-weighted NLP demo"}


def find_similar_complaint(title: str, description: str, candidates, threshold: float = 0.54):
    """Return the closest issue using Jaccard overlap over meaningful tokens."""
    stop = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "at", "is", "are", "has", "have", "for", "with", "our", "my", "please", "near", "since", "there", "been", "this", "that"}
    incoming = set(_tokens(f"{title} {description}")) - stop
    if not incoming:
        return None
    best, best_score = None, 0
    for item in candidates:
        words = set(_tokens(f"{item.title} {item.description}")) - stop
        score = len(incoming & words) / max(len(incoming | words), 1)
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= threshold else None
