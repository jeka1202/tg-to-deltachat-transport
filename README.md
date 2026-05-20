# tg-to-deltachat-transport

Минимальный транспорт (мост) Telegram ↔ Delta Chat на Python.

## Что уже есть

- Авторизация Telegram-аккаунта через Telethon (user client).
- Настройка/авторизация почтового аккаунта для Delta Chat через `deltachat-rpc-client`.
- **Интерактивный запуск**: если переменные окружения не заданы, скрипт сам задаёт вопросы в терминале.
- Ретрансляция **текстовых** сообщений:
  - Telegram → Delta Chat
  - Delta Chat → Telegram

## Важно про шифрование Delta Chat

Delta Chat сам делает E2EE (Autocrypt/OpenPGP) в своём core. В этом проекте шифрование вручную не реализуется — скрипт передаёт текст в API Delta Chat, а отправка/шифрование выполняются на стороне Delta Chat core.

## Быстрый старт (VPS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bridge.py
```

Скрипт задаст вопросы про:
- Telegram API ID / API HASH
- target Telegram
- почтовые параметры Delta Chat (email, пароль, IMAP/SMTP)
- target email для Delta Chat

Если хотите полностью неинтерактивный режим, можно заранее выставить env-переменные (см. `.env.example`).

При первом запуске Telethon попросит код подтверждения Telegram (и пароль 2FA, если включен).

## Минимальные ограничения текущей версии

- Только 1 Telegram target и 1 Delta Chat target.
- Только текстовые сообщения.
- Нет хранения mapping по множеству чатов/контактов.
- Простейшая защита от relay-loop.

Это MVP, на котором уже можно строить полноценный транспорт «как раньше джаббер↔аська», добавляя маршрутизацию, вложения, retries и более строгую дедупликацию.
