"""Inspect complete reviewer evidence without assuming it is inline in the bootstrap."""

import hashlib
import json


def original_review_prompt(runner, entry, reviewer, *, branch):
    """Read the public immutable resource protocol; this does not acknowledge native delivery."""
    transport = entry.get("context_transport")
    if not transport:
        return entry["prompt"]
    chunks = []
    offset = 0
    while True:
        request = {"type": "context_request", "context_id": transport["context_id"],
                   "resource_id": "prompt", "offset": offset}
        result = runner.serve_review_context(reviewer, json.dumps(request), transport["round_id"], branch=branch)
        assert result["status"] == "context_response", result
        assert result["offset"] == offset
        raw = result["content"].encode("utf-8")
        assert hashlib.sha256(raw).hexdigest() == result["chunk_sha256"]
        chunks.append(raw)
        if result["eof"]:
            combined = b"".join(chunks)
            assert len(combined) == result["total_bytes"] == transport["original_prompt_bytes"]
            assert hashlib.sha256(combined).hexdigest() == result["sha256"]
            return combined.decode("utf-8")
        assert result["next_offset"] > offset
        offset = result["next_offset"]
