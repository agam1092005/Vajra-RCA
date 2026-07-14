"""Natural-language explanation layer.

Gemini turns the *already-correlated* structured incident into an operator-readable
narrative (what / where / when / why / supporting evidence / missing evidence). It
does NOT perform detection or causation — that is decided deterministically upstream.
When no API key is configured, a deterministic template produces the same fields so
the system is fully functional offline.
"""
from __future__ import annotations

import json
import time

from ..core.config import settings

_SYSTEM = (
    "You are a senior network reliability engineer assisting with root-cause analysis. "
    "You are given a STRUCTURED incident that has already been correlated and scored by a "
    "deterministic engine. Do NOT invent causes or change the ranking. Explain the top "
    "hypothesis clearly for an on-call operator. Be precise and concise. Never present an "
    "uncertain hypothesis as an absolute conclusion."
)


def _client():
    if not settings.google_api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=settings.google_api_key)
    except Exception:
        return None


def deterministic_explanation(incident: dict) -> dict:
    hyps = incident.get("hypotheses", [])
    top = hyps[0] if hyps else {}
    node = incident.get("focal_node", "the affected node")
    when = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(incident.get("window_start", time.time())))
    confirmed = [e["text"] for e in top.get("confirmed_evidence", [])]
    correlated = [e["text"] for e in top.get("correlated_signals", [])]
    missing = [e["text"] for e in top.get("missing_evidence", [])]
    conf = int(top.get("confidence", 0) * 100)
    why = (f"The engine ranks this cause at {conf}% confidence based on: "
           + ", ".join(f"{k} (+{v})" for k, v in top.get("score_breakdown", {}).items()) + ".")
    narrative = (
        f"What: {incident.get('title','Anomaly detected')}. "
        f"Where: {node}"
        + (f" (blast radius {incident.get('blast_radius',{}).get('count',0)} downstream nodes). " if incident.get('blast_radius') else ". ")
        + f"When: activity began around {when}. "
        + f"Why: {top.get('root_cause','unknown')} — {why} "
        + (f"Supporting evidence: {confirmed[0]} " if confirmed else "")
        + (f"Still missing: {missing[0]}" if missing else "")
    )
    return {
        "what": incident.get("title"), "where": node, "when": when,
        "why": why, "supporting_evidence": confirmed, "correlated_signals": correlated,
        "missing_evidence": missing, "narrative": narrative, "generated_by": "deterministic",
    }


def explain_incident(incident: dict) -> dict:
    client = _client()
    base = deterministic_explanation(incident)
    if client is None:
        return base
    prompt = (
        _SYSTEM + "\n\nIncident (JSON):\n" + json.dumps(_slim(incident), indent=2)
        + "\n\nReturn a JSON object with keys: what, where, when, why, supporting_evidence "
          "(list), missing_evidence (list), narrative (a 3-4 sentence operator summary)."
    )
    try:
        resp = client.models.generate_content(
            model=settings.gemini_model, contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(resp.text)
        data["generated_by"] = settings.gemini_model
        # keep deterministic fields as fallback for any the model omitted
        for k, v in base.items():
            data.setdefault(k, v)
        return data
    except Exception as exc:  # network/quota/parse — degrade gracefully
        base["llm_error"] = str(exc)[:200]
        return base


def chat(incident: dict, question: str) -> dict:
    client = _client()
    if client is None:
        top = (incident.get("hypotheses") or [{}])[0]
        return {"answer": (f"[offline] Most probable cause of the incident on {incident.get('focal_node')} is "
                           f"{top.get('root_cause','unknown')} ({int(top.get('confidence',0)*100)}% confidence). "
                           f"Set VAJRA_GOOGLE_API_KEY to enable conversational analysis."),
                "generated_by": "deterministic"}
    prompt = (_SYSTEM + "\n\nIncident (JSON):\n" + json.dumps(_slim(incident), indent=2)
              + f"\n\nOperator question: {question}\nAnswer grounded ONLY in the incident data above.")
    try:
        resp = client.models.generate_content(model=settings.gemini_model, contents=prompt)
        return {"answer": resp.text, "generated_by": settings.gemini_model}
    except Exception as exc:
        return {"answer": f"LLM unavailable ({str(exc)[:120]}).", "generated_by": "error"}


def _slim(incident: dict) -> dict:
    """Trim the incident to the fields the LLM needs (keeps prompt small)."""
    return {
        "title": incident.get("title"), "focal_node": incident.get("focal_node"),
        "severity": incident.get("severity"), "summary": incident.get("summary"),
        "blast_radius": incident.get("blast_radius", {}).get("count"),
        "signal_counts": incident.get("signal_counts"),
        "hypotheses": [
            {k: h.get(k) for k in ("rank", "root_cause", "kind", "confidence", "score_breakdown",
                                    "confirmed_evidence", "correlated_signals", "missing_evidence")}
            for h in incident.get("hypotheses", [])[:3]
        ],
        "timeline": incident.get("timeline", [])[:12],
    }
