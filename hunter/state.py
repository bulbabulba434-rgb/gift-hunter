from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from .config import ROOT

STATE_FILE = ROOT / "state" / "state.json"
SEEN_TTL = 7 * 24 * 3600


@dataclass
class State:
    seen: dict = field(default_factory=dict)  # slug -> {"price", "ts", "collection", "model"}
    update_offset: int = 0
    budget: float | None = None  # overrides config max_price_stars when set via /budget
    paused: bool = False
    last_top: list = field(default_factory=list)  # pre-formatted HTML
    last_scan: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)  # collection -> [[ts, floor], ...]
    watch: dict = field(default_factory=dict)  # key -> {"collection", "model", "max_price", ...}
    hidden: list = field(default_factory=list)  # collection titles the user muted
    names: list = field(default_factory=list)  # collection titles seen in the last scan
    day: str = ""  # local date the day_* counters belong to
    day_deals: dict = field(default_factory=dict)  # slug -> summary of the best deals today
    day_scans: int = 0
    digest_sent: str = ""  # local date of the last digest

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
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(STATE_FILE)

    def mark_seen(self, slug: str, price: float, collection: str = "", model: str | None = None) -> None:
        self.seen[slug] = {"price": price, "ts": int(time.time()), "collection": collection, "model": model}

    def is_hidden(self, title: str) -> bool:
        return title.lower() in (h.lower() for h in self.hidden)
