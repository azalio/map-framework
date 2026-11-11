"""Shared paraphrase fixture for reviewer envelopes (#670).

Every /map-review reviewer output must open with a ``paraphrase`` object. Test
payloads that stand in for a real reviewer get it from here, so one edit keeps
every fixture valid when the paraphrase contract changes.
"""

from typing import Any

PARAPHRASE: dict[str, str] = {
    "change": "The change sets VALUE to 2 in writer.py. Nothing else in the module moves.",
    "existing_system": "writer.py holds one module-level constant that callers read directly.",
}


def with_paraphrase(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with the shared paraphrase unless it already carries one."""
    return {"paraphrase": dict(PARAPHRASE), "discarded_candidates": [], **payload}
