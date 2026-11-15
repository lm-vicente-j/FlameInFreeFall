"""Proposed canonical material names, awaiting human review.

These are suggestions only (proposed_by "llm", review "pending"). Names are
lowercase. Compound entries ("PMMA & Nomex") stay compound: splitting them would
be an inference the source does not make. "SIBAL" is the cotton-fiberglass blend
fabric flown on Saffire, so both spellings map to one name.
"""

MATERIAL_PROPOSALS: dict[str, str] = {
    "Methanol": "methanol",
    "Heptane": "heptane",
    "SIBAL Fabric": "cotton-fiberglass fabric (sibal)",
    "Cotton-Fiberglass (SIBAL)": "cotton-fiberglass fabric (sibal)",
    "Silicone": "silicone",
    "PMMA": "pmma",
    "PMMA & Nomex": "pmma and nomex",
}
