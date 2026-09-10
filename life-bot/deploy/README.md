# Выкат

Машина: Linux, Python 3.11 или новее. Проверить: `python3 --version`.
На Ubuntu 22.04 штатный Python — 3.10, проект на нём не запустится: нужен
`tomllib`, появившийся в 3.11. Ставить из PPA `deadsnakes` либо брать 24.04.

## 1. Пользователь и код

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin lifebot
sudo mkdir -p /opt/life-bot && sudo chown lifebot:lifebot /opt/life-bot
sudo -u lifebot git clone <репозиторий> /opt/life-bot
cd /opt/life-bot
sudo -u lifebot python3 -m venv .venv
sudo -u lifebot .venv/bin/pip install -r requirements.txt
sudo -u lifebot .venv/bin/pip install -r requirements-voice.txt   # расшифровка голоса
```

## 2. Конфиг

```bash
sudo -u lifebot cp config.example.toml config.toml
sudo -u lifebot chmod 600 config.toml
sudoedit -u lifebot /opt/life-bot/config.toml
```

Заполнить `telegram.token`, `telegram.owner_id` и, если нужен внешний контроль,
`heartbeat.url` с healthchecks.io. Файл в репозиторий не попадает.

## 3. Служба

```bash
sudo cp deploy/life-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now life-bot
systemctl status life-bot
journalctl -u life-bot -f
```

Убить процесс и убедиться, что systemd поднял его сам:

```bash
sudo systemctl kill -s SIGKILL life-bot && sleep 7 && systemctl status life-bot
```

## 4. Сон и питание

Домашняя машина по умолчанию засыпает — тогда бот замолкает.

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

В BIOS включить автостарт после пропадания питания (`Restore on AC Power Loss`).

## 5. Бэкап

Копия рядом с оригиналом бэкапом не является: нужен второй хост. Для отправки
завести ключ без пароля и положить публичную часть на приёмник.

```bash
sudo -u lifebot ssh-keygen -t ed25519 -N '' -f /home/lifebot/.ssh/backup_ed25519
sudo -u lifebot ssh-copy-id -i /home/lifebot/.ssh/backup_ed25519.pub root@ПРИЁМНИК
```

Пароль шифрования. Хранить вне сервера: потеряешь — копии станут мусором.

```bash
sudo -u lifebot bash -c 'openssl rand -base64 32 > /opt/life-bot/deploy/backup.pass'
sudo -u lifebot chmod 600 /opt/life-bot/deploy/backup.pass
sudo -u lifebot cp deploy/backup.env.example deploy/backup.env
sudo -u lifebot chmod 600 deploy/backup.env
sudoedit -u lifebot /opt/life-bot/deploy/backup.env
```

Таймер:

```bash
sudo cp deploy/life-bot-backup.service deploy/life-bot-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now life-bot-backup.timer
systemctl list-timers life-bot-backup
```

Проверить сразу, не дожидаясь ночи:

```bash
sudo systemctl start life-bot-backup && journalctl -u life-bot-backup -n 20
```

## 6. Проверка восстановления

Раз в месяц. Копия, которую ни разу не разворачивали, бэкапом не считается.

```bash
sudo -u lifebot bash -c 'set -a; . /opt/life-bot/deploy/backup.env; set +a; /opt/life-bot/deploy/restore-check.sh'
```

Скрипт расшифровывает последнюю копию, проверяет целостность и сравнивает
число записей с рабочей базой.

## Что где лежит

| Путь | Что |
|---|---|
| `/opt/life-bot/config.toml` | Токен и настройки, права 600 |
| `/opt/life-bot/var/life_bot.db` | База |
| `/opt/life-bot/var/files/` | Фото и голосовые |
| `/opt/life-bot/var/backups/` | Зашифрованные копии |
| `/opt/life-bot/deploy/backup.pass` | Пароль шифрования копий |
| `journalctl -u life-bot` | Логи службы |
