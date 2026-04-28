"""Anomaly screening for anti-doping monitoring (rule-based; swap for trained ML later)."""

from __future__ import annotations


def metric_flags(vitals: dict, baseline: dict) -> list[str]:
    hr, hrv, hb, cort = vitals["hr"], vitals["hrv"], vitals["hb"], vitals["cortisol"]
    b = baseline
    flags: list[str] = []
    if hr > b["hr"] + 18 or hr < b["hr"] - 12:
        flags.append("HR")
    if hrv < b["hrv"] - 18:
        flags.append("HRV")
    if hb > b["hb"] + 1.2:
        flags.append("Hb")
    if cort > b["cortisol"] + 6:
        flags.append("Cortisol")
    return flags


def anomaly_score(vitals: dict, baseline: dict) -> tuple[float, list[str]]:
    flags = metric_flags(vitals, baseline)
    score = 0.06 + 0.13 * len(flags)
    for f in flags:
        if f == "Hb":
            score += 0.06
        if f == "Cortisol":
            score += 0.05
    return min(0.98, round(score, 4)), flags


def risk_status(score: float, flags: list[str]) -> str:
    if len(flags) >= 2 or score >= 0.78:
        return "critical"
    if len(flags) >= 1 or score >= 0.52:
        return "elevated"
    return "normal"


def doping_suspected(score: float, flags: list[str]) -> bool:
    return risk_status(score, flags) == "critical"
