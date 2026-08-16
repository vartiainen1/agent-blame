"""agent-blame - a deterministic Git archaeology engine.

Given a file:line target, agent-blame reconstructs the historical context
around that code: what introduced it, how it evolved, what counter-evidence
exists, how confident the analysis is, and what historical removal risk the
evidence suggests.

The core is purely algorithmic and deterministic. No LLM, no network, no
randomness. The repository is the source of truth; the algorithm decides
which evidence matters.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
