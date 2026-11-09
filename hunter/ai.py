"""Short buy/skip commentary from Google Gemini (free tier). Optional: failures are logged and ignored."""
from __future__ import annotations

import json
import logging

import httpx

from .models import Deal

log = logging.getLogger(__name__)
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FALLBACK_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]
LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"


def _discover(api_key: str) -> list[str]:
    """Text 'flash' models the key can use right now, newest first (Google retires old ones often)."""
    try:
        data = httpx.get(LIST_URL, headers={"x-goog-api-key": api_key}, timeout=30).json()
    except Exception:
        return []
    names = [m["name"].split("/")[-1] for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    skip = ("tts", "image", "preview", "omni", "latest")
    return sorted((n for n in names if "flash" in n and not any(s in n for s in skip)), reverse=True)

PROMPT = """Ты помощник коллекционера Telegram NFT-подарков. Ниже лоты с маркета перепродажи,
которые алгоритм отметил как интересные. Цены в Telegram Stars (⭐).
Для каждого лота дай вердикт: "брать", "присмотреться" или "пропустить",
и комментарий на русском в 1–2 предложения: чем цена или редкость интересна и какой главный риск
(мало лотов для сравнения, низкая ликвидность, редкость не влияет на цену у этой коллекции и т.п.).
Не обещай прибыль и не выдумывай данные, которых нет.
Верни только JSON-массив объектов вида {"slug": "...", "verdict": "...", "comment": "..."}.

Лоты:
"""


def _payload(d: Deal) -> dict:
    l = d.listing
    return {
        "slug": l.slug,
        "collection": l.collection,
        "number": f"#{l.num} из {l.total}",
        "price_stars": round(d.price),
        "collection_floor_stars": round(d.floor),
        "price_vs_floor": f"x{d.premium:.2f}",
        "next_same_model_stars": round(d.next_same_model) if d.next_same_model else None,
        "attributes": {a.kind: f"{a.name} ({a.percent:.1f}%)" if a.percent else a.name for a in l.attrs.values()},
        "listed_in_collection": d.listed_in_collection,
        "signals": d.reasons,
        "telegram_value_info": d.value,
    }


def explain(deals: list[Deal], api_key: str, model: str) -> None:
    if not deals or not api_key:
        return
    body = {
        "contents": [{"parts": [{"text": PROMPT + json.dumps([_payload(d) for d in deals], ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    models = [model] + [m for m in FALLBACK_MODELS if m != model]
    models += [m for m in _discover(api_key) if m not in models][:4]
    for m in models:
        try:
            r = httpx.post(URL.format(model=m), json=body, headers={"x-goog-api-key": api_key}, timeout=60)
            if r.status_code in (404, 429, 500, 503):
                log.warning("Gemini (%s): HTTP %s, пробую другую модель", m, r.status_code)
                continue
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            items = json.loads(text)
            by_slug = {i.get("slug"): i for i in items if isinstance(i, dict)}
            for d in deals:
                if (i := by_slug.get(d.listing.slug)):
                    d.ai = {"verdict": str(i.get("verdict", "")), "comment": str(i.get("comment", ""))}
            return
        except Exception as e:
            log.warning("Gemini (%s) не ответил: %s", m, e)
            continue
