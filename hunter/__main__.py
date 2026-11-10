"""python -m hunter <command>

  run     один скан + уведомления (так запускает GitHub Actions)
  loop    работать постоянно на своём ПК (бот отвечает сразу)
  demo    проверить логику на выдуманных данных, без Telegram (--send — прислать примеры в бота)
  login   получить TG_SESSION для своего аккаунта
  chatid  узнать свой CHAT_ID (сначала напиши боту /start)
"""
from __future__ import annotations

import logging
import random
import sys

from .config import Secrets, load_config


def demo(cfg: dict, sec: Secrets, send: bool = False) -> None:
    from . import ai
    from .fmt import format_deal
    from .models import Attr, Listing
    from .scoring import analyze_collection

    rnd = random.Random(7)
    models = [("Gold", 5), ("Pixel", 12), ("Kitty", 25), ("Basic", 30), ("Frost", 28)]
    backdrops = [("Onyx Black", 6), ("Emerald", 15), ("Sky Blue", 20), ("Grey", 25)]
    symbols = [("Crown", 3), ("Star", 9), ("Heart", 15), ("Dot", 20)]
    listings = []
    for n in range(80):
        m, b, s = rnd.choice(models), rnd.choice(backdrops), rnd.choice(symbols)
        price = int(3000 * (1 + rnd.random()) * (1.8 if m[1] < 10 else 1))
        listings.append(Listing(1, "Demo Pepe", f"DemoPepe-{n + 900}", n + 900, 50000, price, price / 200,
                                {"model": Attr("model", *m), "backdrop": Attr("backdrop", *b),
                                 "symbol": Attr("symbol", *s)}))
    # planted bargains
    listings.append(Listing(1, "Demo Pepe", "DemoPepe-42", 42, 50000, 3100, 15.5,
                            {"model": Attr("model", "Basic", 30), "backdrop": Attr("backdrop", "Grey", 25),
                             "symbol": Attr("symbol", "Dot", 20)}))
    listings.append(Listing(1, "Demo Pepe", "DemoPepe-7777", 7777, 50000, 3600, 18.0,
                            {"model": Attr("model", "Gold", 5), "backdrop": Attr("backdrop", "Onyx Black", 6),
                             "symbol": Attr("symbol", "Crown", 3)}))
    deals = sorted(analyze_collection(listings, cfg, 200, len(listings)), key=lambda d: d.score, reverse=True)
    top = deals[: cfg["max_alerts_per_run"]]
    if sec.gemini_key and cfg["ai"]["enabled"]:
        ai.explain(top, sec.gemini_key, cfg["ai"]["model"])
    print(f"Найдено сделок: {len(deals)} из {len(listings)} лотов\n")
    for d in top:
        print(format_deal(d), "\n")

    if send:
        from .app import HELP
        from .bot import Bot
        from .fmt import deal_buttons, format_top

        bot = Bot(sec.bot_token)
        bot.send(sec.chat_id, "🧪 <b>Так теперь выглядят сообщения</b> (выдуманные данные)")
        bot.send(sec.chat_id, HELP)
        for d in top[:2]:
            bot.send(sec.chat_id, format_deal(d), buttons=deal_buttons(d))
        bot.send(sec.chat_id, format_top(top))
        print("Примеры отправлены в бота.")


def login(sec: Secrets) -> None:
    import re

    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession

    from .config import ROOT

    api_id, api_hash = sec.api_id, sec.api_hash
    if not (api_id and api_hash):
        print("api_id и api_hash бесплатно выдают на https://my.telegram.org → API development tools")
        api_id = int(input("api_id: ").strip())
        api_hash = input("api_hash: ").strip()
    else:
        print("api_id и api_hash взяты из .env")
    print("Сейчас Telegram попросит номер телефона (+7...) и код, который придёт в приложение Telegram.\n")
    with TelegramClient(StringSession(), api_id, api_hash) as c:
        session = c.session.save()
        me = c.get_me()

    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    line = f"TG_SESSION={session}"
    if re.search(r"(?m)^TG_SESSION=", text):
        text = re.sub(r"(?m)^TG_SESSION=.*$", lambda _: line, text)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    env.write_text(text, encoding="utf-8")
    print(f"\n✅ Вход выполнен как {me.first_name}. TG_SESSION сохранена в .env — копировать ничего не нужно.")


def chatid(sec: Secrets) -> None:
    from .bot import Bot

    if not sec.bot_token:
        sys.exit("Сначала укажи BOT_TOKEN в .env")
    seen = set()
    for u in Bot(sec.bot_token).updates(0):
        chat = (u.get("message") or {}).get("chat", {})
        if chat.get("id") not in seen:
            seen.add(chat.get("id"))
            print(f"CHAT_ID={chat.get('id')}  ({chat.get('first_name') or chat.get('title')})")
    if not seen:
        print("Сообщений нет — напиши боту /start и запусти команду ещё раз.")


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    cfg, sec = load_config(), Secrets.from_env()
    if cmd == "demo":
        demo(cfg, sec, send="--send" in sys.argv)
    elif cmd == "login":
        login(sec)
    elif cmd == "chatid":
        chatid(sec)
    elif cmd in ("run", "loop"):
        if missing := sec.missing():
            sys.exit("Не хватает переменных: " + ", ".join(missing) + " (см. README)")
        from .app import loop, run_once
        (run_once if cmd == "run" else loop)(cfg, sec)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
