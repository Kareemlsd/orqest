"""Shared demo tools.

Kept deliberately small and self-contained — these exist to make demos
interesting without network dependencies. Real applications would use
live APIs, MCP servers, or domain-specific Orqest tools.
"""

from __future__ import annotations

from datetime import datetime


async def get_current_time() -> str:
    """Return the current local date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def calculate(expression: str) -> str:
    """Evaluate a simple arithmetic expression."""
    try:
        allowed = set("0123456789+-*/().% ")
        if all(c in allowed for c in expression):
            return f"{expression} = {eval(expression)}"  # noqa: S307
        return "Invalid expression"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


async def analyze_topic(topic: str) -> str:
    """Return high-level analysis of a topic."""
    return (
        f"Analysis of '{topic}':\n"
        f"- Complex topic with multiple dimensions\n"
        f"- Key areas: fundamentals, applications, recent developments\n"
        f"- Recommendation: break into subtopics for deeper analysis"
    )


# --- Research demo: mock web search ---

_FIXTURE_SOURCES: dict[str, list[dict[str, str]]] = {
    "nuclear": [
        {
            "title": "Nuclear energy trade-offs — IEA 2026 report",
            "url": "https://www.iea.org/reports/nuclear-energy-2026",
            "snippet": (
                "Global nuclear capacity reached 430 GW in 2026. Low-carbon "
                "baseload continues to grow, but construction costs remain "
                "dominant risk factor. SMRs entering commercial deployment."
            ),
        },
        {
            "title": "Public opinion on nuclear — Pew Research 2026",
            "url": "https://www.pewresearch.org/2026/nuclear-power",
            "snippet": (
                "US support for expanded nuclear reached 55% in 2026 polling, "
                "up from 43% in 2020. Safety concerns persist post-Fukushima, "
                "but decarbonization framing increasingly favors it."
            ),
        },
        {
            "title": "Waste management challenges — Nature 2026",
            "url": "https://www.nature.com/articles/nuclear-waste-2026",
            "snippet": (
                "No permanent repository operational globally. Finland's Onkalo "
                "remains the only licensed deep geological facility. Dry cask "
                "storage now considered 100-year interim solution."
            ),
        },
    ],
    "quantum": [
        {
            "title": "Quantum computing commercial progress — McKinsey 2026",
            "url": "https://www.mckinsey.com/quantum-2026",
            "snippet": (
                "Q1 2026 saw IBM, Google, and IonQ announce >1000-qubit systems. "
                "Commercial quantum advantage demonstrated in drug discovery "
                "and logistics optimization."
            ),
        },
        {
            "title": "Post-quantum cryptography NIST standards",
            "url": "https://www.nist.gov/pqc-2026",
            "snippet": (
                "All four finalists (ML-KEM, ML-DSA, SLH-DSA, FN-DSA) now "
                "standardized. Migration timeline calls for full adoption "
                "across federal systems by 2030."
            ),
        },
    ],
    "ai": [
        {
            "title": "State of AI 2026 report",
            "url": "https://www.stateof.ai/2026",
            "snippet": (
                "Agentic AI became the dominant deployment pattern in 2026. "
                "65% of enterprises running production agents, up from 12% "
                "in 2024."
            ),
        },
        {
            "title": "AI Act enforcement — European Commission",
            "url": "https://ec.europa.eu/ai-act-2026",
            "snippet": (
                "High-risk system audits began Q1 2026. First enforcement "
                "actions targeting employment screening and credit scoring "
                "systems with missing impact assessments."
            ),
        },
    ],
    "default": [
        {
            "title": "General reference on the topic",
            "url": "https://example.com/topic",
            "snippet": "Broad overview with context and references.",
        },
        {
            "title": "Recent developments 2026",
            "url": "https://example.com/recent",
            "snippet": "Current state of the field with citations.",
        },
    ],
}


async def web_search(query: str) -> str:
    """Mock web search — returns fixture sources based on keywords.

    Real deployment would call Brave, Serper, Exa, or similar.
    Sources are returned as JSON so the agent can cite them with indices.
    """
    import json

    q = query.lower()
    if "nuclear" in q or "energy" in q:
        sources = _FIXTURE_SOURCES["nuclear"]
    elif "quantum" in q:
        sources = _FIXTURE_SOURCES["quantum"]
    elif "ai" in q or "agent" in q or "llm" in q:
        sources = _FIXTURE_SOURCES["ai"]
    else:
        sources = _FIXTURE_SOURCES["default"]

    # Return numbered results that the agent can cite as [1], [2], etc.
    formatted = [
        {"index": i + 1, "title": s["title"], "url": s["url"], "snippet": s["snippet"]}
        for i, s in enumerate(sources)
    ]
    return json.dumps(formatted, indent=2)
