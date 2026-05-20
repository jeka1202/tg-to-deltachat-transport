#!/usr/bin/env python3
"""
Minimal Telegram <-> Delta Chat bridge.

What it does:
- Authenticates Telegram account via Telethon (user API).
- Configures/logins Delta Chat account via deltachat-rpc-client.
- Relays plain text messages both ways.

Notes:
- Delta Chat encryption (Autocrypt / OpenPGP) is handled by Delta Chat core itself.
  This bridge only forwards message text.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from getpass import getpass
from typing import Dict, Optional

from telethon import TelegramClient, events
from telethon.tl.custom.message import Message as TgMessage

from deltachat_rpc_client import DeltaChat


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tg-dc-bridge")


def ask_value(prompt: str, env_key: str, default: Optional[str] = None, secret: bool = False) -> str:
    env_value = os.getenv(env_key)
    if env_value:
        return env_value

    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            value = getpass(f"{prompt}{suffix}: ").strip()
        else:
            value = input(f"{prompt}{suffix}: ").strip()

        if value:
            return value
        if default is not None:
            return default
        print("Значение обязательно, попробуйте снова.")


@dataclass
class Settings:
    tg_api_id: int
    tg_api_hash: str
    tg_session: str

    dc_email: str
    dc_password: str
    dc_imap_host: str
    dc_imap_port: int
    dc_imap_security: str
    dc_smtp_host: str
    dc_smtp_port: int
    dc_smtp_security: str

    tg_target_username: str
    dc_target_email: str
    dc_accounts_dir: str

    @classmethod
    def from_env_or_prompt(cls) -> "Settings":
        print("=== Настройка Telegram ↔ Delta Chat моста ===")
        return cls(
            tg_api_id=int(ask_value("Telegram API ID", "TG_API_ID")),
            tg_api_hash=ask_value("Telegram API HASH", "TG_API_HASH"),
            tg_session=ask_value("Имя Telegram session файла", "TG_SESSION", default="tg_bridge"),
            dc_email=ask_value("Delta Chat email", "DC_EMAIL"),
            dc_password=ask_value("Delta Chat пароль почты", "DC_PASSWORD", secret=True),
            dc_imap_host=ask_value("IMAP host", "DC_IMAP_HOST"),
            dc_imap_port=int(ask_value("IMAP port", "DC_IMAP_PORT", default="993")),
            dc_imap_security=ask_value("IMAP security (ssl/starttls/plain)", "DC_IMAP_SECURITY", default="ssl"),
            dc_smtp_host=ask_value("SMTP host", "DC_SMTP_HOST"),
            dc_smtp_port=int(ask_value("SMTP port", "DC_SMTP_PORT", default="465")),
            dc_smtp_security=ask_value("SMTP security (ssl/starttls/plain)", "DC_SMTP_SECURITY", default="ssl"),
            tg_target_username=ask_value("Telegram target (@username или id)", "TG_TARGET_USERNAME"),
            dc_target_email=ask_value("Delta Chat target email", "DC_TARGET_EMAIL"),
            dc_accounts_dir=ask_value("Папка данных Delta Chat", "DC_ACCOUNTS_DIR", default="./dc-accounts"),
        )


class TgDcBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tg = TelegramClient(settings.tg_session, settings.tg_api_id, settings.tg_api_hash)
        self.dc = DeltaChat(settings.dc_accounts_dir)
        self._relay_locks: Dict[str, bool] = {"tg_to_dc": False, "dc_to_tg": False}
        self._dc_chat_id: Optional[int] = None
        self._tg_peer = None

    async def setup_telegram(self) -> None:
        log.info("Connecting Telegram...")
        await self.tg.start()
        me = await self.tg.get_me()
        log.info("Telegram authorized as: %s", getattr(me, "username", None) or me.id)
        self._tg_peer = await self.tg.get_entity(self.settings.tg_target_username)
        log.info("Telegram bridge target resolved: %s", self.settings.tg_target_username)

    async def setup_deltachat(self) -> None:
        log.info("Configuring Delta Chat account...")
        account = self.dc.get_account(0) if self.dc.get_all_accounts() else self.dc.add_account()

        account.set_config("addr", self.settings.dc_email)
        account.set_config("mail_pw", self.settings.dc_password)
        account.set_config("mail_server", self.settings.dc_imap_host)
        account.set_config("mail_port", str(self.settings.dc_imap_port))
        account.set_config("mail_security", self.settings.dc_imap_security)
        account.set_config("send_server", self.settings.dc_smtp_host)
        account.set_config("send_port", str(self.settings.dc_smtp_port))
        account.set_config("send_security", self.settings.dc_smtp_security)

        account.configure()
        while True:
            progress = account.get_config("configured")
            if progress == "1":
                break
            await asyncio.sleep(1)

        log.info("Delta Chat configured and ready.")
        contact_id = account.create_contact(self.settings.dc_target_email, self.settings.dc_target_email)
        self._dc_chat_id = account.create_chat_by_contact_id(contact_id)
        log.info("Delta Chat bridge target prepared: %s", self.settings.dc_target_email)

        self._dc_account = account

    async def relay_tg_to_dc(self) -> None:
        @self.tg.on(events.NewMessage(from_users=self._tg_peer))
        async def handler(event: events.NewMessage.Event) -> None:
            msg: TgMessage = event.message
            if not msg.message:
                return
            if self._relay_locks["dc_to_tg"]:
                return
            self._relay_locks["tg_to_dc"] = True
            try:
                text = f"[TG] {msg.message}"
                self._dc_account.send_text_msg(self._dc_chat_id, text)
                log.info("Relayed TG -> DC: %s", text)
            finally:
                self._relay_locks["tg_to_dc"] = False

    async def relay_dc_to_tg_loop(self) -> None:
        last_msg_id = 0
        while True:
            try:
                msgs = self._dc_account.get_fresh_msgs()
                for mid in msgs:
                    if mid <= last_msg_id:
                        continue
                    m = self._dc_account.get_msg(mid)
                    if not m.text:
                        continue
                    if m.chat_id != self._dc_chat_id:
                        continue
                    if self._relay_locks["tg_to_dc"]:
                        continue
                    self._relay_locks["dc_to_tg"] = True
                    try:
                        text = f"[DC] {m.text}"
                        await self.tg.send_message(self._tg_peer, text)
                        log.info("Relayed DC -> TG: %s", text)
                    finally:
                        self._relay_locks["dc_to_tg"] = False
                    last_msg_id = max(last_msg_id, mid)
            except Exception:
                log.exception("Error in DC -> TG loop")
            await asyncio.sleep(1)

    async def run(self) -> None:
        await self.setup_telegram()
        await self.setup_deltachat()
        await self.relay_tg_to_dc()

        log.info("Bridge is running.")
        await asyncio.gather(
            self.tg.run_until_disconnected(),
            self.relay_dc_to_tg_loop(),
        )


def main() -> None:
    settings = Settings.from_env_or_prompt()
    bridge = TgDcBridge(settings)
    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
