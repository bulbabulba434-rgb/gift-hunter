from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "collections": [],
    "exclude_collections": [],
    "pages_per_collection": 1,
    "page_size": 100,
    "request_delay_sec": 0.4,
    "max_runtime_sec": 420,
    "max_price_stars": 0,
    "rare_permille": 10,
    "rare_ratio": 0.5,
    "rare_weights": {"model": 3.0, "backdrop": 2.0, "symbol": 1.0},
    "min_comparables": 2,
    "max_premium_for_rare": 1.6,
    "min_gap": 0.15,
    "low_number": 100,
    "min_score": 4.5,
    "max_alerts_per_run": 5,
    "ton_to_stars_fallback": 200,
    "loop_interval_sec": 300,
    "ai": {"enabled": True, "model": "gemini-flash-lite-latest", "max_deals": 5},
}


def load_config(path: Path | None = None) -> dict:
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    path = path or ROOT / "config.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Secrets:
    api_id: int
    api_hash: str
    session: str
    bot_token: str
    chat_id: str
    gemini_key: str

    @classmethod
    def from_env(cls) -> "Secrets":
        _load_dotenv()
        g = os.environ.get
        raw_id = (g("TG_API_ID") or "").strip()
        if raw_id and not raw_id.isdigit():
            print("⚠ TG_API_ID должен быть числом (App api_id с my.telegram.org), а не api_hash", file=sys.stderr)
            raw_id = ""
        return cls(
            api_id=int(raw_id or 0),
            api_hash=g("TG_API_HASH", ""),
            session=g("TG_SESSION", ""),
            bot_token=g("BOT_TOKEN", ""),
            chat_id=g("CHAT_ID", ""),
            gemini_key=g("GEMINI_API_KEY", ""),
        )

    def missing(self) -> list[str]:
        need = {"TG_API_ID": self.api_id, "TG_API_HASH": self.api_hash, "TG_SESSION": self.session,
                "BOT_TOKEN": self.bot_token, "CHAT_ID": self.chat_id}
        return [k for k, v in need.items() if not v]
