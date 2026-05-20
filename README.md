# tg-to-deltachat-transport

Транспорт Telegram ↔ Delta Chat без фейковых email-адресов.

## Новая концепция (для mail.ru и других строгих провайдеров)

Вместо создания фейковых контактов вида `tg-123@telegram.local`:

- используется **один реальный чат Delta Chat** с вашим реальным email (`DC_OPERATOR_EMAIL`);
- все входящие из Telegram приходят туда в формате:
  - `[tg-123456 | Ivan] текст сообщения`
- чтобы ответить в Telegram нужному контакту, пишите команду:
  - `/to tg-123456 ваш ответ`

Так мы не создаём невалидные email и не упираемся в ограничения mail.ru.

## Что умеет

- Авторизация Telegram (Telethon)
- Авторизация Delta Chat почты (IMAP/SMTP)
- Интерактивный конфиг при запуске
- Подтягивание личных Telegram чатов и их ID
- Приём сообщений от разных TG-контактов в Delta Chat
- Отправка из Delta Chat разным TG-контактам по `/to tg-<id> ...`

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bridge.py
```
