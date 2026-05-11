"""Stable identifiers for external news sources."""
from hashlib import sha256


def stable_source_id(value: str, namespace: str = "source") -> int:
    """Return a deterministic positive SQLite-friendly integer ID."""
    normalized = f"{namespace}:{value.strip().lower()}".encode("utf-8")
    # Keep IDs below JavaScript's Number.MAX_SAFE_INTEGER because the admin
    # panel receives them through JSON and uses them in API paths.
    digest = sha256(normalized).hexdigest()[:13]
    return int(digest, 16)
