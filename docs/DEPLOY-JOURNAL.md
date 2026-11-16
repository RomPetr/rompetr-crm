# Журнал разработки и деплоя CRM

**Назначение:** восстановить цепь событий и понять, что и где исправить при переносе на VPS.
**Формат:** новые записи добавляются в конец хронологии. Блоки `[VPS]` — приоритетные действия на сервере.
**Время:** локальное UTC+8. Репозиторий: `C:\Users\rp\course\content`.

---

## 1. Чек-лист деплоя на VPS (держать в актуальном состоянии)

### 1.1. Перед первым push в публичный GitHub

- [ ] Выполнить `python -I scripts/git_guard.py --tracked` → код 0.
- [ ] Проверить `git ls-files`: не должно быть `posts/`, `var/`, `*.png`, `.env`, `.claude/env.txt`, `.mcp-servers/`.
- [ ] Ключи VK/TG/ProxyAPI **не ротировались** по решению пользователя. Считать их локально известными; в git они не попадают. При компрометации — заменить.
- [ ] Создать публичный репозиторий, remote `origin`, первый push.
- [ ] В GitHub включить secret scanning и push protection.

### 1.2. Сервер Debian 12

- [ ] Установить: `python3.11`, `python3.11-venv`, `build-essential`, `libpq-dev`, `postgresql-16`, `nginx`, `certbot`, `python3-certbot-nginx`, `git`, `ufw`, `fail2ban`, `logrotate`, `bubblewrap`, `socat`.
- [ ] Создать пользователей `cpapp` (web) и `cpworker` (worker), группу `cpmedia`.
- [ ] Разложить код в `/srv/rompetr/crm`, venv в `/srv/rompetr/venv`.
- [ ] `pip install -r requirements.txt`.
- [ ] Создать PostgreSQL-роли: `rompetr_app` (DML), `rompetr_migrator` (DDL), `rompetr_backup` (read-only). Запустить `scripts/init_db.py` или SQL вручную.
- [ ] `alembic upgrade head` под `rompetr_migrator`.
- [ ] Проверить триггер `trg_users_protect_root` и индекс `ux_users_one_admin`.

### 1.3. `/etc/rompetr-crm/app.env` (600 root)

Обязательные отличия от локального `.env`:

```text
APP_ENV=prod
APP_BASE_URL=https://rompetr.ru
APP_SECRET_KEY=<новый длинный random>
COOKIE_SECURE=true
DATABASE_URL=postgresql+psycopg://rompetr_app:<пароль>@127.0.0.1:5432/rompetr
ADM_PASSW=<новый пароль ≥16 символов>
WORKER_INPROCESS=false
CLAUDE_CODE_OAUTH_TOKEN=<из claude setup-token>
CLAUDE_CONFIG_DIR=/var/lib/rompetr-claude
EMAIL_MODE=dev            # до настройки SMTP; письма в var/mail/
```

Не передавать воркеру `ANTHROPIC_API_KEY`: иначе биллинг уйдёт на API вместо подписки.

### 1.4. systemd

- [ ] `rompetr-migrate.service` — oneshot, `alembic upgrade head`, `Before=rompetr-web.service`.
- [ ] `rompetr-web.service` — `uvicorn webapp.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers`, пользователь `cpapp`.
- [ ] `rompetr-worker.service` — `python -m webapp.worker`, пользователь `cpworker`, `WORKER_INPROCESS` не включать.
- [ ] Таймеры backup/cleanup, `certbot.timer`.
- [ ] Hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ReadWritePaths` на `var/`, `posts/`, конфиг Claude.

### 1.5. Claude Code на VPS

- [ ] `claude setup-token` на машине с браузером, токен в `app.env`.
- [ ] `claude auth status` под `cpworker` → `authMethod: oauth_token`.
- [ ] Один раз запустить `claude` в `/srv/rompetr/crm` под `cpworker`, принять trust.
- [ ] Проверить: `claude -p "reply OK" --max-turns 1` → exit 0.
- [ ] Не использовать `--bare` (не читает OAuth).
- [ ] `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` уже выставляется в runner.

### 1.6. nginx, TLS, сеть

- [ ] `server_name rompetr.ru www.rompetr.ru`; HTTP → HTTPS.
- [ ] `client_max_body_size 12m`.
- [ ] `/static/` — alias; `/media/` — proxy на приложение (там проверка прав).
- [ ] `limit_req` на `/login`, `/register`, `/forgot-password`.
- [ ] Security headers и CSP (Alpine CSP-сборка, если появится).
- [ ] UFW: только 22/80/443; fail2ban включить.
- [ ] Сертификат: DNS-01 заранее или HTTP-01 после переключения A-записи.
- [ ] Старый сервер `185.154.20.52` не трогать 48 часов после переключения.

### 1.7. Проверка после деплоя

- [ ] `curl -fsS https://rompetr.ru/healthz` → ok.
- [ ] Вход админом, регистрация нового пользователя, verify из `var/mail/`.
- [ ] Черновик → Checker → Pixly → одобрение → публикация в тестовый VK/TG.
- [ ] `/admin/jobs`: `ai_check` через `claude -p` завершается успешно.
- [ ] `systemctl status rompetr-web rompetr-worker`; reboot; повторная проверка.
- [ ] `certbot renew --dry-run`; restore из `pg_dump` в отдельную БД.

### 1.8. Известные ловушки

- [VPS] Установщик PostgreSQL может не создать роль `postgres`: `scripts/pg_recover.ps1` решает через временный `trust` на localhost; `postgres --single` под администратором Windows запрещён.
- [VPS] IPv6-loopback может быть заблокирован: подключаться к `127.0.0.1`, не к `localhost`.
- [VPS] `ALTER ROLE ... PASSWORD` не принимает bind-параметры — только SQL-литерал.
- [VPS] ClaudeRunner прокидывает только whitelisted env; на Windows нужны `SystemRoot`, `PATHEXT`, `APPDATA`.
- [VPS] X автоматически не публикуется: только ручная очередь `manual_pending` + intent-ссылка.
- [VPS] VK-токен сообщества не умеет `photos.*`: только текст.
- [VPS] Старый `/publish` использует `bot.py`, `cp_vk_publish.py`, Pixly-скрипты в `.cache`; они читают `.env`.

---

## 2. Хронология

### 2026-11-15 — план и фундамент

- Утверждён план CRM: FastAPI + Jinja2/HTMX, PostgreSQL 16, systemd + nginx, monorepo `content/` + `webapp/`, публичный GitHub.
- Решения пользователя: локально PostgreSQL 16; e-mail пока dev; гость создаёт черновик без публикации; X — ручной режим; репозиторий публичный.
- Созданы `.gitignore`, `.gitattributes`, `.env.example`, `README.md`.
- `scripts/git_guard.py`: allowlist/denylist, скан секретов, лимит 10 МБ; хуки `.githooks/pre-commit`, `pre-push`.
- `scripts/migrate_env.py` перенёс 56 переменных из `.claude/env.txt` в `.env`; legacy-файлы затем удалены.
- Установлен PostgreSQL 16. Установщик не создал роль `postgres`; восстановление выполнено `scripts/pg_recover.ps1` через временный localhost `trust`. Исправлена ошибка `ALTER ROLE ... PASSWORD $1`.
- Каркас `webapp/`: config, db, logging, security headers, 13 таблиц, Alembic, лендинг, health.
- Этап 2: Argon2id, сессии в БД, CSRF, rate limit, регистрация → verify → тикет, админ ID 0, защита триггером, админка users/tickets.
- `scripts/check_keys.py` проверяет ключи без вывода значений и ищет legacy-копии.

### 2026-11-16 09:20 — Этап 3: черновики и медиа

- Pydantic-схема поста, лимиты площадок, запрет секретов и обещаний доходности.
- CRUD черновиков с optimistic lock, статусы `draft → pending_review → approved/rejected`.
- Загрузка PNG/JPEG: проверка сигнатуры, перекодирование в PNG без EXIF, дедупликация SHA-256, приватная выдача `/media/...`.
- Модерация в `/admin/posts`; аудит действий.
- Тесты: 13 → позже 18.

### 2026-11-16 10:20 — ссылка на главную издания в черновике

- В форме черновика появилось read-only поле с URL главной страницы выбранного издания, кнопка «Скопировать» и кликабельная ссылка.
- `webapp/static/js/publisher.js` (внешний файл из-за CSP).

### 2026-11-16 10:40 — Этап 4: публикация

- `services/vk.py`: `wall.post`, `error 27` без retry.
- `services/telegram.py`: `sendPhoto`, caption ≤1024, разбиение длинного текста, retry.
- `services/publish.py`: идемпотентность `(post_id, platform)`, статус `unknown` без авто-повтора.
- Ручная очередь X: `manual_pending`, intent-ссылка; админ отмечает публикацию в `/admin/publications`.
- `python -m webapp.cli publish-due` — публикация по `scheduled_at`.
- `scripts/smoke_publish.py --dry-run`.

### 2026-11-16 10:45 — `-no_post` и MD

- `/publish -no_post` готовит JSON, Checker, Pixly и MD, но не публикует.
- `scripts/json_to_md.py` пишет `<base>.md` с реальными переносами строк.
- Пустой флаг `-no_post` трактуется как немедленный запуск.

### 2026-11-16 11:15 — модерация в списке черновиков

- `/drafts` под админом: столбец автора (ID · логин), кнопки «Подтвердить»/«Отклонить» прямо в списке.
- На странице поста: «Модерация: одобрено · admin (ID 0) · дата».
- На реальной БД обнаружены два черновика «второй» от `chuttkii` в `pending_review`.

### 2026-11-16 12:30 — Этап 5: очередь и worker

- `jobs`: idempotency, `FOR UPDATE SKIP LOCKED`, stale-requeue, retry с backoff.
- `ClaudeRunner`: `dontAsk`, tool allowlist, env allowlist, timeout + kill tree, JSON-логи.
- `ai_check`: JSON поста → `var/jobs/<job>/post.json` → `claude -p` → валидация → применение, `version+1`.
- `generate_image`: ProxyAPI flux.2-pro, резерв gpt-image-1-mini, сохранение через медиа-сервис.
- Админ-страница `/admin/jobs`, кнопки постановки задач в черновике.
- Локально `claude -p` работает через `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` текущей сессии. `ANTHROPIC_API_KEY` в runner заблокирован.
- Встроенный dev-worker: `WORKER_INPROCESS=true` запускает поток внутри FastAPI; на VPS — отдельный systemd worker.

### 2026-11-16 13:00 — журнал и админ-ссылки

- На `/admin` цифры стали ссылками: пользователи, pending, тикеты, посты, задачи.
- `/admin/users?status=pending` — фильтр; столбцы «Имя / логин», роль, статус, подтверждение e-mail.
- Создан этот журнал.

---

## 3. Открытые вопросы

| ID | Вопрос | Текущее допущение |
|---|---|---|
| Q1 | SMTP-провайдер и ADMIN_EMAIL | dev-режим, письма в `var/mail/` |
| Q2 | DNS и способ сертификата | DNS-01, TTL 300 |
| Q3 | VPS: IP, ресурсы, SSH | 2 vCPU / 4 ГБ / 40 ГБ |
| Q4 | Правит ли гость черновик после отправки | Нет |
| Q5 | Кто публикует | user — свой approved, guest — никогда |
| Q6 | Модель Claude для worker | `sonnet` + fallback `haiku` |
| Q7 | Импорт старых JSON | Оставить на диске |
| Q8 | Offsite-бэкапы | Backblaze B2 через restic |

---

## 4. Что ещё не сделано

- HTMX-фрагменты: формы работают обычными POST с перезагрузкой.
- Роль `moderator` — только в планах.
- Планировщик `scheduled_at` есть в CLI, но нет поля в UI черновика.
- Telegram-письма SMTP, публичный GitHub remote и push.
- Деплой на VPS и переключение worker’а на systemd.
