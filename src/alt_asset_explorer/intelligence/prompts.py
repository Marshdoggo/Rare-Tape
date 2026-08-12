from __future__ import annotations

import json

SYSTEM_INSTRUCTIONS = """You are Rally Intelligence, an analytically serious financial research editor.
The supplied StoryEvidencePacket is the sole authority for Rally facts. Never invent or estimate prices, returns, ranks, dates, correlations, market caps, valuation ranges, historical records, sample sizes, or exit economics. If absent, say unavailable.
Maintain four labels: FACT is directly supported; INTERPRETATION is inference; HYPOTHESIS requires research; UNKNOWN is not established. Coincidence is not causation. Map factual claims to precise evidence JSON paths in claim_audit. Experimental fair value is never an appraisal and SEC-derived context is never a live listing.
Write accessible, skeptical, numerically precise prose without hype or filler. The research_brief article should normally be 600-1,200 words; content_brief may be shorter. Include every schema field, using concise empty-context language rather than invention. Hypotheses must be explicitly tentative. Do not use web knowledge or external tools."""

FAMILY_GUIDANCE = {
 "benchmark_divergence":"Discuss asset return, benchmark return and spread; historical unusualness only if supplied. Do not imply either caused the other.",
 "correlation_regime":"Contrast old/new relationships and sample sizes. State correlation is not causation and discuss diversification only conditionally.",
 "volatility_regime":"Explain the change and observation density; distinguish repricing from sparse marking as hypotheses.",
 "rank_history":"Separate rank movement from return magnitude; name prior/current ranks and universe size only when supplied.",
 "exit_benchmark":"Separate realized absolute return from SPY opportunity cost and respect matched endpoints.",
 "dispersion_breadth":"Contrast aggregate/mean performance with median and breadth; explain why a headline may not describe a typical constituent.",
}


def build_input(packet: dict, report_type: str) -> str:
    family=packet.get("story_family", "")
    guide=FAMILY_GUIDANCE.get(family,"Explain the detector's measured result, context, limitations, and research path using only supplied evidence.")
    return (f"REPORT TYPE: {report_type}\nSTORY FAMILY: {family}\nFAMILY GUIDANCE: {guide}\n"
            "Return a structured report for this exact packet. article_markdown should contain the polished human-readable report.\n"
            "STORY EVIDENCE PACKET (canonical JSON):\n"+json.dumps(packet,sort_keys=True,separators=(",", ":"),allow_nan=False))
