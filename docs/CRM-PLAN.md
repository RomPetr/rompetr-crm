# CRM публикации новостей — план и чек-лист

**Домен:** rompetr.ru · **Прод:** отдельный VPS Debian 12 · **Статус:** этап 0
**Полная версия плана:** `C:\Users\rp\.claude\plans\agile-painting-thacker.md`
**Машинная спецификация:** `.claude/plans/crm-web-platform.yaml`

---

## Зачем это

Сейчас Content Plant управляется только с одного компьютера: JSON-посты, субагенты,
`/publish`, внешние скрипты. Нет входа, пользователей, истории задач, планировщик
живёт только пока открыт Claude Code.

CRM на rompetr.ru должна дать:

- страницу входа по адресу домена;
- регистрацию с подтверждением e-mail;
- админа ID `#0` (login `admin`, пароль из `ADM_PASSW`);
- гостевой доступ и тикет новому пользователю в админке;
- черновики, проверку, картинку, публикацию в VK/Telegram;
- в будущем — любые темы, не только DEX/DeFi;
- Claude Code с подпиской внутри проекта;
- локальную обкатку, затем деплой на VPS через публичный GitHub.

---

## Решения

| Область | Решение |
|---|---|
| Backend | FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, psycopg 3 |
| Frontend | Jinja2 + HTMX + Alpine (CSP) + Tailwind (собран заранее) |
| БД | PostgreSQL 16 локально и на VPS |
| Auth | Сессии в БД, Argon2id, CSRF, rate limit |
| E-mail | dev-режим (файл + лог), SMTP перед продом |
| Гость | Черновик и картинка; публикация запрещена |
| X | Ручная очередь (intent-ссылка + URL) |
| Очередь | Таблица `jobs` + worker, без Redis |
| Claude | `claude -p` на задание, 1 процесс, `dontAsk` |
| Репозиторий | Monorepo, приложение `webapp/`, GitHub **публичный** |
| Деплой | systemd + venv + nginx + certbot, без Docker |

---

## Архитектура

```text
Браузер → nginx (TLS, rate limit) → FastAPI (Jinja2/HTMX)
                                      ├─ auth / sessions / CSRF
                                      ├─ drafts / tickets / admin
                                      └─ jobs в PostgreSQL
                                             ↓
                                    worker (claude -p, images, VK, Telegram)
                                             ↓
                                    PostgreSQL + var/media
```

Claude Code читает и правит JSON, но **не публикует**. Публикация — только
детерминированный Python-код после действия пользователя или админа.

---

## Этапы

### Этап 0. Подготовка и git — сейчас
- [x] `.gitignore`, `.gitattributes`, `.env.example`, `README.md`
- [x] `scripts/git_guard.py`, `.githooks/pre-commit`, `pre-push`
- [x] `scripts/install_hooks.py`, `scripts/migrate_env.py`
- [ ] `git init -b main`, первый коммит
- [ ] Публичный GitHub-репозиторий, remote `origin`
- [ ] `.env` создан, ключи VK/TG/ProxyAPI ротированы
- [ ] PostgreSQL 16 локально
- [ ] GitHub secret scanning и push protection включены

**Приёмка:** `git check-ignore` закрывает `posts/`, `.chrome-x-profile/`,
`.mcp-servers/`, `.claude/env.txt`, `.env`; `git ls-files` без медиа и секретов;
`git_guard --tracked` → 0.

### Этап 1. Скелет приложения и БД
- [ ] `webapp/` config, db, main, logging, health
- [ ] SQLAlchemy-модели всех таблиц
- [ ] Alembic initial + trigger защиты ID 0
- [ ] `base.html`, Tailwind, HTMX/Alpine локально
- [ ] `pyproject.toml`, requirements, pytest на PostgreSQL

**Приёмка:** `alembic upgrade head`; `/healthz` и `/` → 200; `pytest -q`; нет
Windows-путей в коде.

### Этап 2. Auth + регистрация + админ
- [ ] Argon2id, сессии, CSRF, rate limit, email tokens
- [ ] Bootstrap админа, защита ID 0, CLI смены пароля
- [ ] Регистрация → verify → guest + тикет
- [ ] Админские users/tickets, аудит

**Приёмка:** письмо в `var/mail/`; verify создаёт тикет; CSRF → 403; лимит → 429;
ID 0 нельзя удалить или сменить роль; смена `ADM_PASSW` не перезаписывает пароль.

### Этап 3. Дашборд, черновики, тикеты — готово
- [x] CRUD черновиков, схема, optimistic lock
- [x] Загрузка PNG/JPEG: sniff, re-encode, strip EXIF, ≤10 МБ
- [x] Статусы, модерация, приватная отдача медиа

**Приёмка:** гость создаёт черновик; публикация → 403; чужой черновик → 404;
действия в `audit_log`.

### Этап 4. Публикация VK/Telegram
- [ ] `telegram.py`, `vk.py`, `publish.py`, `x_manual.py`
- [ ] Идемпотентность, retry, статус `unknown`
- [ ] Планировщик `scheduled_at`
- [ ] `smoke_publish.py --dry-run`

**Приёмка:** нет дублей; caption ≤1024; `error 27` без retry; X → `manual_pending`;
токенов в логах нет.

### Этап 5. Claude Code worker
- [ ] `jobs`, worker loop, `ClaudeRunner`, timeout, lock
- [ ] `ai_check`, `generate_image`
- [ ] Админ-экран jobs
- [ ] OAuth-токен и trust на VPS

**Приёмка:** ≤1 Claude одновременно; timeout убивает процесс; stale-lock возвращает
задачу; `claude auth status` → `oauth_token`.

### Этап 6. Локальная обкатка
- [ ] ruff, pytest, покрытие ≥70%
- [ ] Ручной сценарий до публикации в тестовые VK/TG
- [ ] Restore из `pg_dump`
- [ ] `git_guard --tracked` → 0

### Этап 7. Деплой на VPS
- [ ] Provisioning Debian 12, PostgreSQL, systemd, nginx, certbot, UFW, fail2ban
- [ ] Бэкапы, logrotate
- [ ] DNS-переключение

**Приёмка:** HTTPS с валидным сертификатом; вход и регистрация; публикация в тестовый
канал; reboot; `certbot renew --dry-run`; restore; старый сервер не изменён.

### Этап 8. gitpublisher и CI
- [ ] `.claude/agents/gitpublisher.md`
- [ ] GitHub Actions: ruff, pytest, guard, alembic
- [ ] Защита `main`, тег `v0.1.0`

**Приёмка:** guard блокирует `posts/x.png` (2), `.env` (2), `sk-...` (3), >10 МБ (4);
CI зелёный.

---

## Вопросы к вам (ответьте по ID)

| ID | Вопрос | Если не ответите |
|---|---|---|
| [Q1] | SMTP-провайдер и `ADMIN_EMAIL` | dev-режим; затем Яндекс 360 |
| [Q2] | Кто управляет DNS и способ сертификата | DNS-01, TTL 300 |
| [Q3] | VPS: vCPU/RAM/диск, IP, SSH | 2 vCPU / 4 ГБ / 40 ГБ, IP на этапе 7 |
| [Q4] | Гость правит черновик после отправки? Любые PNG/JPEG? | Нет; PNG/JPEG с валидацией |
| [Q5] | Кто публикует: только админ или user свой approved? | user — свой; guest — никогда |
| [Q6] | Модель Claude: `sonnet` + fallback `haiku`? | Да, алиасы |
| [Q7] | Импортировать 33 старых JSON в БД? | Нет, оставить на диске |
| [Q8] | Offsite-бэкапы: S3, B2, Яндекс? | Backblaze B2 через restic |

---

## Проверка

**Локально:** `alembic upgrade head` → регистрация → письмо в `var/mail/` → verify →
тикет → одобрение → черновик → картинка → проверка → публикация в тестовые каналы →
`pytest`, `ruff`, `git_guard --tracked` → restore БД.

**На VPS:** `curl https://rompetr.ru/healthz` → вход → регистрация → публикация →
`systemctl status` → reboot → `ufw status` → `fail2ban-client status` →
`certbot renew --dry-run` → `claude auth status`.

---

## Что не входит в MVP

Публичный API, rich-text, импорт старых постов, мультиязычность, object storage,
мобильное приложение, X API, автоматический фактчекинг.
