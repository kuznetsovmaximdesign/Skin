# Личный бот

Telegram-бот для одного пользователя: заметки, напоминания, списки, питание.
Текст, голос, фото. Задание — в `docs/`, читать начиная с `docs/life_bot_spec.md`.

Сделан этап 1 «Труба»: входящее сохраняется в `inbox_raw` до любого разбора.
Разбора, напоминаний и команд ещё нет — это этапы 2 и дальше.

## Что уже работает

- Приём текста, голоса, фото, пересланных сообщений и файлов.
- Запись в `inbox_raw` с видом `text | voice | photo | forward` — до скачивания
  файла и до расшифровки. Сбой сети или whisper пишется в поле `error`,
  сообщение остаётся.
- Расшифровка голоса локальным faster-whisper. Выключается в конфиге.
- Фото и аудио складываются в `var/files/ГГГГ-ММ-ДД/<id файла>`.
- Реакция 👀 на принятое сообщение — единственный ответ на этом этапе.
- Повтор того же `tg_message_id` в течение минуты не создаёт вторую строку.
- Чужие сообщения игнорируются: бот отвечает только `telegram.owner_id`.

## Запуск

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-voice.txt   # если нужен голос

cp config.example.toml config.toml
chmod 600 config.toml                              # секреты не в исходниках
$EDITOR config.toml                                # token и owner_id

.venv/bin/python -m life_bot
```

Путь к конфигу переопределяется переменной `LIFE_BOT_CONFIG`.
База, файлы и лог по умолчанию лежат в `var/` рядом с конфигом.

## Тесты

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Telegram и whisper в тестах заменены заглушками, сеть не нужна.

## Устройство

| Файл | Что делает |
|---|---|
| `life_bot/config.py` | Конфиг из TOML, проверка прав 600 |
| `life_bot/db.py` | SQLite в WAL, схема из `docs/life_bot_schema.sql` как есть |
| `life_bot/intake.py` | Слой 0: вид сообщения, запись, файл, расшифровка, реакция |
| `life_bot/voice.py` | faster-whisper, модель грузится лениво |
| `life_bot/bot.py` | Каркас aiogram, фильтр владельца, запуск |

## Чего в этапе 1 намеренно нет

Systemd-юнит, heartbeat на healthchecks.io и бэкап на maxmini отложены до
выката на VPS — по спеке они часть этапа 1, приёмочные сценарии 2 и 3 без
сервера не проверить. Схема данных при этом уже применяется целиком.
