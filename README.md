# tg-to-deltachat-transport

Многоконтактный MVP-транспорт Telegram ↔ Delta Chat на Python.

## Что теперь умеет

- Авторизация Telegram-аккаунта (Telethon).
- Настройка/авторизация почтового аккаунта Delta Chat.
- Интерактивный запуск (если env не заданы, скрипт спрашивает всё в консоли).
- Подтягивание **личных чатов Telegram** при старте.
- Назначение каждому Telegram контакту bridge-ID в формате `tg-<telegram_user_id>`.
- Создание отдельного чата в Delta Chat на каждый Telegram контакт.
- Двунаправленная ретрансляция текста:
  - Telegram (разные личные контакты) → их отдельные чаты в Delta Chat
  - Delta Chat (из конкретного bridge-чата) → соответствующему контакту в Telegram

## Как работает ID и маршрутизация

- Для Telegram пользователя с `id=123456` создаётся bridge-ID: `tg-123456`.
- В Delta Chat создаётся контакт/чат с псевдо-адресом `tg-123456@telegram.local`.
- Все входящие из этого Telegram контакта идут именно в этот чат Delta Chat.
- Любой ваш ответ в этом чате Delta Chat уходит обратно Telegram-пользователю `123456`.

## Важно про шифрование Delta Chat

Delta Chat сам делает E2EE (Autocrypt/OpenPGP) в core. Скрипт не шифрует сообщения вручную — только передаёт payload в API Delta Chat.

## Быстрый старт (VPS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bridge.py
```
