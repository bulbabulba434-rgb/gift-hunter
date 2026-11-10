"""Minimal Telegram Bot API client (sending messages and reading commands)."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class Bot:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = httpx.Client(timeout=60)

    def call(self, method: str, **params):
        r = self.http.post(self.base + method, json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"{method}: {data.get('description')}")
        return data["result"]

    def send(self, chat_id: str | int, text: str, buttons: list[list[dict]] | None = None) -> None:
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "link_preview_options": {"is_disabled": True}}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        try:
            self.call("sendMessage", **params)
        except Exception as e:
            log.error("Не удалось отправить сообщение: %s", e)

    def updates(self, offset: int, timeout: int = 0) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message"])
