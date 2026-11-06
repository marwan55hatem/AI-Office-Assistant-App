"""A small in-process cache for the heavy report queries.

Entries are keyed by company and request, live for ``ttl`` seconds (so a chart can be
up to that old) and are dropped at once when something that changes the numbers by
hand happens (tasks, people). Sessions syncing in every few seconds do *not* clear the
cache: reports are about days and weeks, and 30 s of staleness keeps the database calm.

It is per server process. With several instances each keeps its own copy, which only
means a little more database work, never wrong data across companies: the company id is
part of every key.
"""
import threading
import time
import uuid
from collections import OrderedDict


class ReportCache:
    def __init__(self, ttl: float = 30.0, max_entries: int = 500, clock=time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict = OrderedDict()
        self._versions: dict[uuid.UUID, int] = {}
        self.hits = 0
        self.misses = 0

    def get(self, company_id: uuid.UUID, key):
        full = (company_id, key)
        with self._lock:
            entry = self._entries.get(full)
            if entry is not None:
                expires, version, value = entry
                if expires > self._clock() and version == self._versions.get(company_id, 0):
                    self._entries.move_to_end(full)
                    self.hits += 1
                    return value
                del self._entries[full]
            self.misses += 1
            return None

    def set(self, company_id: uuid.UUID, key, value) -> None:
        with self._lock:
            self._entries[(company_id, key)] = (self._clock() + self.ttl, self._versions.get(company_id, 0), value)
            self._entries.move_to_end((company_id, key))
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, company_id: uuid.UUID) -> None:
        """Forget everything cached for one company."""
        with self._lock:
            self._versions[company_id] = self._versions.get(company_id, 0) + 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._versions.clear()
            self.hits = self.misses = 0


report_cache = ReportCache()
