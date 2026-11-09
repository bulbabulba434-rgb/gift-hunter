from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from .config import ROOT

STATE_FILE = ROOT / "state" / "state.json"
SEEN_TTL = 7 * 24 * 3600


@dataclass
class State:
    seen: dict = field(default_factory=dict)  # slug -> {"price": float, "ts": int}
    update_offset: int = 0
    budget: float | None = None  # overrides config max_price_stars when set via /budget
    paused: bool = False
    last_top: list = field(default_factory=list)  # pre-formatted HTML
    last_scan: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        now = time.time()
        self.seen = {k: v for k, v in self.seen.items() if now - v.get("ts", 0) < SEEN_TTL}
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    def mark_seen(self, slug: str, price: float) -> None:
        self.seen[slug] = {"price": price, "ts": int(time.time())}
