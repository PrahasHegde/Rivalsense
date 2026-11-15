"""Explicit single-process demo quota for read-only provider requests.

Default remains the existing database quota. Trusted capture NEVER uses this
limiter. Local mode is opt-in and must use one server process; no outage fallback.
"""
from collections import defaultdict, deque
from contextlib import contextmanager
import os
from threading import Lock
import time
from fastapi import HTTPException
from app.services.rate_limit import extraction_budget

class LocalReadBudget:
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, Lock()
        self.events = defaultdict(deque)
        self.active = defaultdict(int)
        self.global_events = deque()

    @contextmanager
    def reserve(self, user, units):
        try:
            user_limit = int(os.getenv("RIVALSENSE_READS_PER_MINUTE", "10"))
            global_limit = int(os.getenv("RIVALSENSE_GLOBAL_READS_PER_MINUTE", "60"))
            concurrent = int(os.getenv("RIVALSENSE_READ_CONCURRENCY", "2"))
            if not (1 <= user_limit <= 1000 and 1 <= global_limit <= 10000 and 1 <= concurrent <= 10 and 1 <= units <= 5):
                raise ValueError()
        except ValueError:
            raise HTTPException(503, "Invalid provider read-quota settings") from None
        with self.lock:
            now = self.clock()
            while self.global_events and self.global_events[0][0] <= now - 60:
                self.global_events.popleft()
            for owner in list(self.events):
                while self.events[owner] and self.events[owner][0][0] <= now - 60:
                    self.events[owner].popleft()
                if not self.events[owner] and not self.active.get(owner, 0):
                    del self.events[owner]
                    self.active.pop(owner, None)
            if (sum(n for _, n in self.events[user]) + units > user_limit
                    or sum(n for _, n in self.global_events) + units > global_limit
                    or self.active[user] >= concurrent):
                raise HTTPException(429, "Research quota reached. Please try again shortly.", headers={"Retry-After": "60"})
            self.events[user].append((now, units))
            self.global_events.append((now, units))
            self.active[user] += 1
        try:
            yield
        finally:
            with self.lock:
                self.active[user] -= 1

local_budget = LocalReadBudget()

@contextmanager
def reading_budget(repository, units=1):
    mode = os.getenv("RIVALSENSE_READ_BUDGET", "database").lower()
    if mode == "local":
        with local_budget.reserve(repository.user_id, units):
            yield
    elif mode == "database":
        with extraction_budget(repository, units):
            yield
    else:
        raise HTTPException(503, "Invalid provider read-budget configuration")
