from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from telethon.errors import FloodWaitError, RPCError

from . import ai
from .bot import Bot
from .config import Secrets
from .fmt import deal_buttons, format_deal, format_top
from .market import Market
from .models import Deal
from .scoring import analyze_collection, estimate_ton_rate, is_new
from .state import State

log = logging.getLogger(__name__)

DISCLAIMER = "⚠️ <i>Это подсказки алгоритма, а не финансовый совет. Проверяй лот сам перед покупкой.</i>"
HELP = (
    "👋 <b>Я Gift Hunter</b>\n"
    "Ищу редкие и недооценённые NFT-подарки на маркете Telegram и присылаю их сюда.\n\n"
    "<b>Что я умею</b>\n"
    "1. /top — лучшие находки последнего скана\n"
    "2. /budget 5000 — искать только лоты до 5000 ⭐\n"
    "3. /budget off — снять лимит цены\n"
    "4. /pause — выключить уведомления\n"
    "5. /resume — включить обратно\n"
    "6. /status — когда был последний скан\n\n"
    "<b>Как читать находку</b>\n"
    "🔥 — насколько она сильная (до трёх огоньков)\n"
    "🔥 у атрибута — он редкий для этой коллекции\n"
    "🟢 брать · 🟡 присмотреться · 🔴 пропустить — мнение ИИ\n\n" + DISCLAIMER
)


def budget_of(cfg: dict, st: State) -> float:
    return st.budget if st.budget is not None else float(cfg["max_price_stars"] or 0)


def _wanted(title: str, cfg: dict) -> bool:
    t = title.lower()
    inc = [c.lower() for c in cfg["collections"]]
    exc = [c.lower() for c in cfg["exclude_collections"]]
    return (not inc or t in inc) and t not in exc


async def scan(cfg: dict, sec: Secrets, st: State) -> tuple[list[Deal], list[Deal], dict]:
    started = time.monotonic()
    data, errors = [], 0
    async with Market(sec.api_id, sec.api_hash, sec.session) as m:
        gifts = [g for g in await m.collections() if _wanted(g.title or "", cfg)]
        log.info("Коллекций на перепродаже: %d", len(gifts))
        for g in gifts:
            if time.monotonic() - started > cfg["max_runtime_sec"]:
                log.warning("Лимит времени, остальные коллекции в следующий раз")
                break
            try:
                listings, total = await m.listings(g, cfg["pages_per_collection"], cfg["page_size"])
                data.append((listings, total))
            except FloodWaitError as e:
                log.warning("Telegram просит подождать %s c — прерываю скан", e.seconds)
                break
            except RPCError as e:
                errors += 1
                log.warning("%s: %s", g.title, e)
            await asyncio.sleep(cfg["request_delay_sec"])

        flat = [l for ls, _ in data for l in ls]
        rate = estimate_ton_rate(flat, cfg["ton_to_stars_fallback"])
        budget = budget_of(cfg, st)
        deals: list[Deal] = []
        for listings, total in data:
            deals += analyze_collection(listings, cfg, rate, total, budget)
        deals.sort(key=lambda d: d.score, reverse=True)

        fresh = [d for d in deals if is_new(d, st.seen)][: cfg["max_alerts_per_run"]]
        for d in fresh:
            d.value = await m.value_info(d.listing.slug)

    stats = {
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "collections": len(data),
        "listings": len(flat),
        "deals": len(deals),
        "new": len(fresh),
        "errors": errors,
        "ton_rate": round(rate, 1),
    }
    return deals, fresh, stats


def handle_commands(bot: Bot, cfg: dict, sec: Secrets, st: State, timeout: int = 0) -> None:
    try:
        ups = bot.updates(st.update_offset, timeout)
    except Exception as e:
        log.warning("getUpdates: %s", e)
        return
    for u in ups:
        st.update_offset = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat or not text.startswith("/"):
            continue
        if sec.chat_id and chat != str(sec.chat_id):
            bot.send(chat, "Это приватный бот.")
            continue
        cmd, *args = text.split()
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/help"):
            bot.send(chat, HELP + f"\n\nТвой chat_id: <code>{chat}</code>")
        elif cmd == "/top":
            bot.send(chat, "\n".join(st.last_top) if st.last_top else "Пока нет находок — жду следующий скан.")
        elif cmd == "/budget":
            if not args or args[0].lower() in ("off", "0", "нет"):
                st.budget = 0
                bot.send(chat, "Лимит цены снят.")
            elif args[0].isdigit():
                st.budget = float(args[0])
                bot.send(chat, f"Ищу лоты до {int(st.budget)} ⭐.")
            else:
                bot.send(chat, "Пример: /budget 5000")
        elif cmd == "/pause":
            st.paused = True
            bot.send(chat, "Пауза. /resume — включить обратно.")
        elif cmd == "/resume":
            st.paused = False
            bot.send(chat, "Снова ищу.")
        elif cmd == "/status":
            s = st.last_scan
            b = budget_of(cfg, st)
            bot.send(chat, "\n".join([
                "📡 <b>Статус</b>",
                "",
                f"1. Последний скан: {s.get('time', 'ещё не было')}",
                f"2. Коллекций: {s.get('collections', 0)}",
                f"3. Лотов просмотрено: {s.get('listings', 0)}",
                f"4. Находок: {s.get('deals', 0)} (новых: {s.get('new', 0)})",
                f"5. Лимит цены: {str(int(b)) + ' ⭐' if b else 'нет'}",
                f"6. Режим: {'⏸ на паузе' if st.paused else '▶️ работаю'}",
            ]))


def run_once(cfg: dict, sec: Secrets) -> None:
    st = State.load()
    bot = Bot(sec.bot_token)
    handle_commands(bot, cfg, sec, st)
    if st.paused:
        log.info("На паузе")
        st.save()
        return

    deals, fresh, stats = asyncio.run(scan(cfg, sec, st))
    log.info("Скан: %s", stats)
    if cfg["ai"]["enabled"] and sec.gemini_key:
        ai.explain(fresh[: cfg["ai"]["max_deals"]], sec.gemini_key, cfg["ai"]["model"])
    for d in fresh:
        bot.send(sec.chat_id, format_deal(d), buttons=deal_buttons(d))
        st.mark_seen(d.listing.slug, d.price)
    st.last_top = [format_top(deals[:5])]
    st.last_scan = stats
    st.save()


def loop(cfg: dict, sec: Secrets) -> None:
    """Local always-on mode: scan every N seconds, answer commands instantly in between."""
    bot = Bot(sec.bot_token)
    while True:
        try:
            run_once(cfg, sec)
        except Exception:
            log.exception("Скан упал, попробую в следующий раз")
        deadline = time.time() + cfg["loop_interval_sec"]
        while (left := deadline - time.time()) > 1:
            st = State.load()
            handle_commands(bot, cfg, sec, st, timeout=int(min(30, left)))
            st.save()
