"""Inspect complete reviewer evidence without assuming it is inline in the bootstrap."""

import hashlib
import json


def fetch_review_resource(runner, entry, reviewer, resource, *, branch):
    """Read one frozen resource through the public protocol; this does not acknowledge native delivery."""
    transport = entry["context_transport"]
    chunks = []
    offset = 0
    while True:
        request = {"type": "context_request", "context_id": transport["context_id"],
                   "resource_id": resource, "offset": offset}
        result = runner.serve_review_context(reviewer, json.dumps(request), transport["round_id"], branch=branch)
        assert result["status"] == "context_response", result
        assert result["offset"] == offset
        raw = result["content"].encode("utf-8")
        assert hashlib.sha256(raw).hexdigest() == result["chunk_sha256"]
        chunks.append(raw)
        if result["eof"]:
            combined = b"".join(chunks)
            assert len(combined) == result["total_bytes"]
            assert hashlib.sha256(combined).hexdigest() == result["sha256"]
            return combined.decode("utf-8")
        assert result["next_offset"] > offset
        offset = result["next_offset"]


def original_review_prompt(runner, entry, reviewer, *, branch):
    """Read the complete original prompt resource."""
    transport = entry.get("context_transport")
    if not transport:
        return entry["prompt"]
    prompt = fetch_review_resource(runner, entry, reviewer, "prompt", branch=branch)
    assert len(prompt.encode("utf-8")) == transport["original_prompt_bytes"]
    return prompt


def review_evidence_text(runner, entry, reviewer, *, branch):
    """Original prompt plus the required diff resource: everything the reviewer is told to read as the change."""
    text = original_review_prompt(runner, entry, reviewer, branch=branch)
    if entry.get("context_transport"):
        text += "\n" + fetch_review_resource(runner, entry, reviewer, "diff", branch=branch)
    return text
