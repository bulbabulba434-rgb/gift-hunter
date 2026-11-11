from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from html import escape

from telethon.errors import FloodWaitError, RPCError

from . import ai
from . import tracking as tr
from .bot import Bot
from .config import Secrets
from .fmt import deal_buttons, format_deal, format_top, open_button
from .market import Market
from .models import Deal
from .scoring import analyze_collection, effective_price, estimate_ton_rate, is_new
from .state import State

log = logging.getLogger(__name__)

DISCLAIMER = "⚠️ <i>Это подсказки алгоритма, а не финансовый совет. Проверяй лот сам перед покупкой.</i>"
COMMANDS = [
    ("top", "лучшие находки последнего скана"),
    ("watch", "следить за коллекцией или моделью"),
    ("watchlist", "мой вотчлист"),
    ("unwatch", "убрать из вотчлиста"),
    ("digest", "сводка за сутки"),
    ("budget", "лимит цены в звёздах"),
    ("hidden", "скрытые коллекции"),
    ("unhide", "вернуть скрытую коллекцию"),
    ("status", "статус бота"),
    ("pause", "выключить уведомления"),
    ("resume", "включить уведомления"),
    ("help", "справка"),
]
HELP = (
    "👋 <b>Я Gift Hunter</b>\n"
    "Ищу редкие и недооценённые NFT-подарки на маркете Telegram и присылаю их сюда.\n\n"
    "<b>Находки</b>\n"
    "1. /top — лучшие находки последнего скана\n"
    "2. /digest — сводка за сутки (приходит сама каждое утро)\n"
    "3. /budget 5000 — только лоты до 5000 ⭐ (/budget off — без лимита)\n\n"
    "<b>Вотчлист</b>\n"
    "4. /watch Plush Pepe — следить за коллекцией\n"
    "5. /watch Plush Pepe / Kung Fu Pepe 500000 — за моделью, с лимитом цены\n"
    "6. /watchlist — что я отслеживаю, /unwatch 1 — убрать\n\n"
    "<b>Настройка</b>\n"
    "7. /hidden и /unhide — скрытые коллекции\n"
    "8. /pause, /resume — выключить или включить уведомления\n"
    "9. /status — как идут дела\n\n"
    "<b>Как читать находку</b>\n"
    "🔥 — сила находки (до трёх огоньков)\n"
    "🔥 у атрибута — он редкий для коллекции\n"
    "🟢 брать · 🟡 присмотреться · 🔴 пропустить — мнение ИИ\n"
    "⭐ под находкой — следить за моделью, 🔕 — скрыть коллекцию\n\n" + DISCLAIMER
)


def budget_of(cfg: dict, st: State) -> float:
    return st.budget if st.budget is not None else float(cfg["max_price_stars"] or 0)


def _wanted(title: str, cfg: dict) -> bool:
    t = title.lower()
    inc = [c.lower() for c in cfg["collections"]]
    exc = [c.lower() for c in cfg["exclude_collections"]]
    return (not inc or t in inc) and t not in exc


class Hunter:
    def __init__(self, cfg: dict, sec: Secrets):
        self.cfg, self.sec = cfg, sec
        self.bot = Bot(sec.bot_token)
        self.lock = threading.RLock()
        self.st = State.load()

    def local_now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=self.cfg["tz_offset_hours"])

    def send(self, text: str, buttons=None) -> None:
        self.bot.send(self.sec.chat_id, text, buttons)

    # ---------------- bot updates ----------------

    def poll_updates(self, timeout: int = 0) -> bool:
        try:
            ups = self.bot.updates(self.st.update_offset, timeout)
        except Exception as e:
            log.warning("getUpdates: %s", e)
            return False
        for u in ups:
            with self.lock:
                self.st.update_offset = u["update_id"] + 1
                try:
                    if "callback_query" in u:
                        self.on_callback(u["callback_query"])
                    elif "message" in u:
                        self.on_message(u["message"])
                except Exception:
                    log.exception("Ошибка при обработке команды")
                self.st.save()
        return True

    def _owner(self, chat: str) -> bool:
        return not self.sec.chat_id or chat == str(self.sec.chat_id)

    def on_callback(self, cq: dict) -> None:
        chat = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        if not self._owner(chat):
            self.bot.answer(cq["id"], "Это приватный бот.")
            return
        action, _, slug = (cq.get("data") or "").partition(":")
        info = self.st.seen.get(slug)
        if not info or not info.get("collection"):
            self.bot.answer(cq["id"], "Этот лот уже устарел.")
            return
        coll, model = info["collection"], info.get("model")
        if action == "w":
            key = tr.watch_key(coll, model)
            self.st.watch.setdefault(key.lower(), {"collection": coll, "model": model, "max_price": None})
            self.bot.answer(cq["id"], f"⭐ Слежу: {key}")
            self.bot.send(chat, f"⭐ Добавил в вотчлист: <b>{escape(key)}</b>\n"
                                "Напишу, когда флор упадёт. Список: /watchlist")
        elif action == "h":
            if not self.st.is_hidden(coll):
                self.st.hidden.append(coll)
            self.bot.answer(cq["id"], f"🔕 Больше не покажу {coll}")
            self.bot.send(chat, f"🔕 Скрыл коллекцию <b>{escape(coll)}</b>. Вернуть: /unhide {escape(coll)}")

    def on_message(self, msg: dict) -> None:
        chat = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat or not text.startswith("/"):
            return
        if not self._owner(chat):
            self.bot.send(chat, "Это приватный бот.")
            return
        cmd, _, rest = text.partition(" ")
        cmd, rest = cmd.split("@")[0].lower(), rest.strip()
        reply = lambda t: self.bot.send(chat, t)  # noqa: E731
        st, cfg = self.st, self.cfg

        if cmd in ("/start", "/help"):
            reply(HELP + f"\n\nТвой chat_id: <code>{chat}</code>")
        elif cmd == "/top":
            reply("\n".join(st.last_top) if st.last_top else "Пока нет находок — жду следующий скан.")
        elif cmd == "/budget":
            if not rest or rest.lower() in ("off", "0", "нет"):
                st.budget = 0
                reply("✅ Лимит цены снят.")
            elif rest.replace(" ", "").isdigit():
                st.budget = float(rest.replace(" ", ""))
                reply(f"✅ Ищу лоты до {int(st.budget)} ⭐.")
            else:
                reply("Пример: /budget 5000")
        elif cmd == "/pause":
            st.paused = True
            reply("⏸ Пауза. /resume — включить обратно.")
        elif cmd == "/resume":
            st.paused = False
            reply("▶️ Снова ищу.")
        elif cmd == "/status":
            s, b = st.last_scan, budget_of(cfg, st)
            reply("\n".join([
                "📡 <b>Статус</b>", "",
                f"1. Последний скан: {s.get('time', 'ещё не было')}",
                f"2. Коллекций: {s.get('collections', 0)}, лотов: {s.get('listings', 0)}",
                f"3. Находок: {s.get('deals', 0)} (новых: {s.get('new', 0)})",
                f"4. В вотчлисте: {len(st.watch)}, скрыто коллекций: {len(st.hidden)}",
                f"5. Лимит цены: {str(int(b)) + ' ⭐' if b else 'нет'}",
                f"6. Режим: {'⏸ на паузе' if st.paused else '▶️ работаю'}",
            ]))
        elif cmd == "/watch":
            self.cmd_watch(rest, reply)
        elif cmd == "/unwatch":
            keys = list(st.watch)
            key = keys[int(rest) - 1] if rest.isdigit() and 0 < int(rest) <= len(keys) else rest.lower()
            if key in st.watch:
                w = st.watch.pop(key)
                reply(f"✅ Убрал из вотчлиста: {escape(tr.watch_key(w['collection'], w.get('model')))}")
            else:
                reply("Не нашёл. Посмотри номер в /watchlist и напиши, например, /unwatch 1")
        elif cmd == "/watchlist":
            reply(tr.format_watchlist(st.watch))
        elif cmd == "/hidden":
            if st.hidden:
                reply("🔕 <b>Скрытые коллекции</b>\n\n" + "\n".join(
                    f"{i}. {escape(h)}" for i, h in enumerate(st.hidden, 1)) + "\n\nВернуть: /unhide номер")
            else:
                reply("Скрытых коллекций нет. Скрыть можно кнопкой 🔕 под находкой.")
        elif cmd == "/unhide":
            idx = int(rest) - 1 if rest.isdigit() else next(
                (i for i, h in enumerate(st.hidden) if h.lower() == rest.lower()), -1)
            if 0 <= idx < len(st.hidden):
                reply(f"✅ Снова показываю {escape(st.hidden.pop(idx))}")
            else:
                reply("Не нашёл. Список: /hidden")
        elif cmd == "/digest":
            reply(tr.format_digest(st.day_deals, st.history, st.day_scans, time.time()))
        else:
            reply("Не знаю такую команду. Список команд: /help")

    def cmd_watch(self, rest: str, reply) -> None:
        if not rest:
            reply("Примеры:\n1. /watch Plush Pepe\n2. /watch Plush Pepe / Kung Fu Pepe\n"
                  "3. /watch Plush Pepe 500000 — написать, когда появится лот до 500 000 ⭐")
            return
        coll, model, price = tr.parse_watch(rest)
        names = self.st.names
        if names:
            exact = next((n for n in names if n.lower() == coll.lower()), None)
            if not exact:
                hint = tr.suggest(coll, names)
                reply(f"Не нашёл коллекцию «{escape(coll)}»." + (f" Может, «{escape(hint)}»?" if hint else ""))
                return
            coll = exact
        key = tr.watch_key(coll, model)
        self.st.watch[key.lower()] = {"collection": coll, "model": model, "max_price": price}
        lines = [f"✅ Слежу: <b>{escape(key)}</b>", "", "Напишу, если:",
                 f"1. флор упадёт на {self.cfg['watch_drop']:.0%} и больше"]
        if price:
            lines.append(f"2. появится лот до {int(price):,} ⭐".replace(",", " "))
        reply("\n".join(lines))

    # ---------------- scanning ----------------

    async def _scan(self):
        cfg, st = self.cfg, self.st
        started = time.monotonic()
        data, errors = [], 0
        async with Market(self.sec.api_id, self.sec.api_hash, self.sec.session) as m:
            gifts = await m.collections()
            with self.lock:
                st.names = sorted({g.title for g in gifts if g.title})
                gifts = [g for g in gifts if _wanted(g.title or "", cfg) and not st.is_hidden(g.title or "")]
            log.info("Коллекций на перепродаже: %d", len(gifts))
            for g in gifts:
                if time.monotonic() - started > cfg["max_runtime_sec"]:
                    log.warning("Лимит времени, остальные коллекции в следующий раз")
                    break
                try:
                    listings, total = await m.listings(g, cfg["pages_per_collection"], cfg["page_size"])
                    if listings:
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
            price_of = lambda l: effective_price(l, rate)  # noqa: E731
            now = time.time()
            floors = {ls[0].collection: min(ps) for ls, _ in data if (ps := [p for l in ls if (p := price_of(l))])}

            with self.lock:
                tr.record_floors(st.history, floors, now)
                budget = budget_of(cfg, st)
                deals: list[Deal] = []
                for listings, total in data:
                    t = tr.trend(st.history, listings[0].collection, now)
                    deals += analyze_collection(listings, cfg, rate, total, budget, t)
                deals.sort(key=lambda d: d.score, reverse=True)
                fresh = [d for d in deals if is_new(d, st.seen)][: cfg["max_alerts_per_run"]]
                alerts = [(w, l, price_of(l), r) for w, l, r in tr.check_watch(st.watch, flat, price_of, cfg["watch_drop"])]

            for d in fresh:
                d.value = await m.value_info(d.listing.slug)

        stats = {
            "time": self.local_now().strftime("%d.%m %H:%M"),
            "collections": len(data),
            "listings": len(flat),
            "deals": len(deals),
            "new": len(fresh),
            "errors": errors,
            "ton_rate": round(rate, 1),
        }
        return deals, fresh, alerts, stats

    def scan_once(self) -> None:
        if self.st.paused:
            log.info("На паузе")
            return
        deals, fresh, alerts, stats = asyncio.run(self._scan())
        log.info("Скан: %s, вотчлист: %d", stats, len(alerts))
        if self.cfg["ai"]["enabled"] and self.sec.gemini_key:
            ai.explain(fresh[: self.cfg["ai"]["max_deals"]], self.sec.gemini_key, self.cfg["ai"]["model"])
        for d in fresh:
            self.send(format_deal(d), deal_buttons(d))
        for w, l, price, reason in alerts:
            self.send(tr.format_watch_alert(w, l, price, reason), open_button(l.link))

        with self.lock:
            st = self.st
            for d in fresh:
                m = d.listing.attrs.get("model")
                st.mark_seen(d.listing.slug, d.price, d.listing.collection, m.name if m else None)
            st.last_top = [format_top(deals[:5])]
            st.last_scan = stats
            st.day_scans += 1
            for d in deals[:20]:
                prev = st.day_deals.get(d.listing.slug)
                if not prev or d.score > prev["score"]:
                    st.day_deals[d.listing.slug] = {"title": f"{d.listing.collection} #{d.listing.num}",
                                                    "price": d.price, "score": d.score, "link": d.listing.link}
            if len(st.day_deals) > 60:
                best = sorted(st.day_deals.items(), key=lambda kv: kv[1]["score"], reverse=True)[:60]
                st.day_deals = dict(best)
            self.maybe_digest()
            st.save()

    def maybe_digest(self) -> None:
        """Morning digest once a day; covers everything since the previous digest."""
        st, local = self.st, self.local_now()
        today = local.strftime("%Y-%m-%d")
        if not st.digest_sent:
            st.digest_sent = today  # first start: begin collecting, send tomorrow
            return
        if local.hour >= self.cfg["digest_hour"] and st.digest_sent != today:
            self.send(tr.format_digest(st.day_deals, st.history, st.day_scans, time.time()))
            st.digest_sent, st.day_deals, st.day_scans = today, {}, 0

    # ---------------- entry points ----------------

    def run_once(self) -> None:
        """One scan (used by GitHub Actions / cron)."""
        self.poll_updates(0)
        self.scan_once()

    def loop(self) -> None:
        """Always-on mode for a server: instant replies + scan every loop_interval_sec."""
        self.bot.set_commands(COMMANDS)
        threading.Thread(target=self._poll_forever, daemon=True, name="bot").start()
        log.info("Работаю постоянно: скан каждые %s с", self.cfg["loop_interval_sec"])
        while True:
            started = time.monotonic()
            try:
                self.scan_once()
            except Exception:
                log.exception("Скан упал, попробую в следующий раз")
            time.sleep(max(30, self.cfg["loop_interval_sec"] - (time.monotonic() - started)))

    def _poll_forever(self) -> None:
        while True:
            if not self.poll_updates(timeout=30):
                time.sleep(5)


def run_once(cfg: dict, sec: Secrets) -> None:
    Hunter(cfg, sec).run_once()


def loop(cfg: dict, sec: Secrets) -> None:
    Hunter(cfg, sec).loop()
