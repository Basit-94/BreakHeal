"""Pre-commit Sentinel Hook & Incremental AST Hash Caching for BreakHeal.

Provides instant incremental audits of git-staged changes before commits are finalized,
using cryptographic AST hashing to skip unchanged functions.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class CacheEntry:
    content_hash: str
    status: str
    timestamp: float


class ASTCache:
    """Persistent local cache for AST verification hashes."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path(".breakheal_cache")
        self.cache_file = self.cache_dir / "cache.json"
        self._entries: Dict[str, CacheEntry] = {}
        self._load()

    def _load(self) -> None:
        if self.cache_file.is_file():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    self._entries[k] = CacheEntry(**v)
            except Exception:
                self._entries = {}

    def save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        serializable = {k: asdict(v) for k, v in self._entries.items()}
        self.cache_file.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    @staticmethod
    def compute_hash(code_content: str) -> str:
        """Compute SHA-256 hash of normalized code content."""
        normalized = "\n".join(line.strip() for line in code_content.splitlines() if line.strip())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def is_cached(self, symbol_key: str, code_content: str) -> bool:
        """Check if symbol content matches the clean cached hash."""
        current_hash = self.compute_hash(code_content)
        entry = self._entries.get(symbol_key)
        if entry and entry.content_hash == current_hash and entry.status in ("CLEAN", "HEALED"):
            return True
        return False

    def update(self, symbol_key: str, code_content: str, status: str) -> None:
        import time
        self._entries[symbol_key] = CacheEntry(
            content_hash=self.compute_hash(code_content),
            status=status,
            timestamp=time.time(),
        )
        self.save()


def get_staged_files(extensions: Optional[List[str]] = None) -> List[Path]:
    """Retrieve list of files currently staged in Git index."""
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = [Path(f.strip()) for f in res.stdout.splitlines() if f.strip()]
        if extensions:
            ext_set = set(extensions)
            files = [f for f in files if f.suffix in ext_set]
        return files
    except Exception:
        return []
