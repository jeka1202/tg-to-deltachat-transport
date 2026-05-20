#!/usr/bin/env python3
"""
Telegram <-> Delta Chat bridge (multi-contact MVP).

- Authenticates Telegram account via Telethon.
- Configures Delta Chat mailbox via deltachat-rpc-client.
- Mirrors Telegram private chats into dedicated Delta Chat chats.
- Routes Delta Chat replies back to the correct Telegram contact.

Delta Chat encryption (Autocrypt/OpenPGP) is handled by Delta Chat core.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from getpass import getpass
from typing import Dict, Optional

from deltachat_rpc_client import DeltaChat
from telethon import TelegramClient, events
from telethon.tl.custom.message import Message as TgMessage

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
        value = getpass(f"{prompt}{suffix}: ").strip() if secret else input(f"{prompt}{suffix}: ").strip()
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
            dc_accounts_dir=ask_value("Папка данных Delta Chat", "DC_ACCOUNTS_DIR", default="./dc-accounts"),
        )


class TgDcBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tg = TelegramClient(settings.tg_session, settings.tg_api_id, settings.tg_api_hash)
        self.dc = DeltaChat(settings.dc_accounts_dir)
        self._dc_account = None
        self._last_dc_msg_id = 0

        # mappings: TG user id <-> Delta Chat chat id
        self.tg_to_dc_chat: Dict[int, int] = {}
        self.dc_chat_to_tg: Dict[int, int] = {}

    async def setup_telegram(self) -> None:
        log.info("Connecting Telegram...")
        await self.tg.start()
        me = await self.tg.get_me()
        log.info("Telegram authorized as: %s", getattr(me, "username", None) or me.id)

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
        while account.get_config("configured") != "1":
            await asyncio.sleep(1)

        self._dc_account = account
        log.info("Delta Chat configured and ready.")

    async def bootstrap_private_chats(self) -> None:
        """Preload Telegram private chats and assign bridge IDs."""
        count = 0
        async for dialog in self.tg.iter_dialogs():
            if not dialog.is_user:
                continue
            user = dialog.entity
            tg_user_id = int(user.id)
            await self.ensure_bridge_chat_for_tg_user(tg_user_id)
            count += 1
        log.info("Bootstrapped %s Telegram private chats.", count)

    async def ensure_bridge_chat_for_tg_user(self, tg_user_id: int) -> int:
        existing = self.tg_to_dc_chat.get(tg_user_id)
        if existing:
            return existing

        user = await self.tg.get_entity(tg_user_id)
        display = getattr(user, "first_name", "") or getattr(user, "username", "") or str(tg_user_id)
        bridge_id = f"tg-{tg_user_id}"
        pseudo_email = f"{bridge_id}@telegram.local"
        dc_name = f"TG {bridge_id} {display}".strip()

        contact_id = self._dc_account.create_contact(pseudo_email, dc_name)
        dc_chat_id = self._dc_account.create_chat_by_contact_id(contact_id)

        self.tg_to_dc_chat[tg_user_id] = dc_chat_id
        self.dc_chat_to_tg[dc_chat_id] = tg_user_id
        log.info("Mapped Telegram user %s -> Delta chat %s (%s)", tg_user_id, dc_chat_id, bridge_id)
        return dc_chat_id

    async def relay_tg_to_dc(self) -> None:
        @self.tg.on(events.NewMessage(incoming=True))
        async def handler(event: events.NewMessage.Event) -> None:
            msg: TgMessage = event.message
            if not msg.message or not event.is_private:
                return
            sender = await event.get_sender()
            tg_user_id = int(sender.id)
            dc_chat_id = await self.ensure_bridge_chat_for_tg_user(tg_user_id)
            text = f"[TG:{tg_user_id}] {msg.message}"
            self._dc_account.send_text_msg(dc_chat_id, text)
            log.info("Relayed TG -> DC (%s): %s", tg_user_id, msg.message)

    async def relay_dc_to_tg_loop(self) -> None:
        while True:
            try:
                for mid in self._dc_account.get_fresh_msgs():
                    if mid <= self._last_dc_msg_id:
                        continue
                    self._last_dc_msg_id = max(self._last_dc_msg_id, mid)
                    m = self._dc_account.get_msg(mid)
                    if not m.text:
                        continue
                    tg_user_id = self.dc_chat_to_tg.get(m.chat_id)
                    if tg_user_id is None:
                        continue
                    text = m.text.strip()
                    if text.startswith("[TG:"):
                        continue
                    await self.tg.send_message(tg_user_id, text)
                    log.info("Relayed DC -> TG (%s): %s", tg_user_id, text)
            except Exception:
                log.exception("Error in DC -> TG loop")
            await asyncio.sleep(1)

    async def run(self) -> None:
        await self.setup_telegram()
        await self.setup_deltachat()
        await self.bootstrap_private_chats()
        await self.relay_tg_to_dc()

        log.info("Bridge is running (multi-contact mode).")
        await asyncio.gather(self.tg.run_until_disconnected(), self.relay_dc_to_tg_loop())


def main() -> None:
    settings = Settings.from_env_or_prompt()
    bridge = TgDcBridge(settings)
    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
