# rompetr-crm — Content Plant для «Разум DEX»

CRM-система для подготовки и публикации новостей в соцсети. Объединяет поиск новости,
редакторскую проверку, генерацию иллюстраций, модерацию и публикацию в VK и Telegram
в одном веб-интерфейсе. Внутри работает Claude Code: он переводит и проверяет тексты,
а также может собрать готовый пост из свежих источников по одной кнопке.

Проект вырос из локального конвейера Content Plant: JSON-посты, субагенты Checker и
Pixly, команда `/publish`. Теперь тот же пайплайн доступен через браузер и базу данных,
с пользователями, ролями, очередью задач и историей публикаций.

---

## Для кого

- **Редактор / SMM-специалист** — готовит посты для криптосообщества: DEX, DeFi, Web3,
  кошельки, безопасность, AI-агенты, торговые роботы.
- **Администратор сообщества** — модерирует черновики, управляет доступами, следит за
  очередью задач и публикациями.
- **Гость / новый пользователь** — знакомится с сервисом, собирает черновик и картинку,
  а публикация открывается после одобрения.
- **Владелец проекта** — разворачивает CRM на своём VPS, подключает соцсети и Claude Code.

---

## Какие боли решает

| Боль | Как решает CRM |
|---|---|
| Новости собираются вручную из пяти сайтов | Кнопка «Сгенерировать новость»: агент читает RSS The Block, The Defiant, Blockworks, CoinDesk, Decrypt и заполняет пост |
| Тексты для пяти площадок пишутся отдельно | Один JSON, разные тексты под лимиты Telegram, VK, Instagram, X и TikTok |
| Легко нарушить лимиты и правила площадок | Валидатор и Checker проверяют длину, язык X, ссылку на источник, секреты и обещания доходности |
| Английский источник нужно переводить | «AI-перевод» переводит только включённые поля на русский, X оставляет английским |
| Картинку приходится искать или рисовать | Pixly генерирует PNG по `image_prompt` через ProxyAPI: Flux.2 Pro или GPT Image 1 mini |
| Публикация в VK и Telegram — ручная рутина | VK `wall.post` и Telegram `sendPhoto` публикуются из интерфейса с идемпотентностью |
| X нельзя автоматизировать | Ручная очередь `manual_pending`, intent-ссылка и локальный Chrome-композер с картинкой |
| Непонятно, кто и что менял | Пользователи, роли, тикеты, аудит действий и журнал публикаций |
| Гость может натворить лишнего | Гость создаёт черновик, но публикация только после одобрения админом |
| Планировщик живёт только пока открыт Claude Code | Очередь `jobs` и `scheduled_at` в БД; запуск по расписанию через CLI/worker |

---

## Что уже работает

- Регистрация с подтверждением e-mail (dev-режим пишет письма в `var/mail/`).
- Вход, сессии в PostgreSQL, Argon2id, CSRF, rate limit, сброс пароля.
- Админ ID `#0`, защита от удаления и смены роли триггером БД.
- Гостевой доступ для проверки: черновик, 1 поиск информации, 2 генерации PNG и 1 публикация после одобрения. Админ задаёт лимиты на `/admin/users`.
- Тикеты новых пользователей в админке, одобрение доступа.
- Черновики: источник, дата, заголовок, URL, тексты пяти площадок, `image_prompt`.
- Чекбоксы площадок: выключенное поле не участвует в проверке, переводе и публикации.
- AI-перевод и проверка включённых полей, метки «Переведено» / «Исправлено».
- Генерация PNG с выбором модели, загрузка своего PNG, скачивание изображения.
- Публикация VK и Telegram, идемпотентность, ручная очередь X.
- Админка: пользователи, тикеты, посты, публикации, задачи.
- Очередь `jobs`, worker, безопасный запуск `claude -p`, логи задач.
- Админская кнопка «Сгенерировать новость»: полный цикл от RSS до картинки.
- Старый конвейер `/publish` с `-no_post` и MD-копией для ручного копирования.

---

## Архитектура

```text
Браузер
  │ HTTPS
  ▼
nginx (TLS, rate limit, static, proxy)
  │ 127.0.0.1:8000
  ▼
FastAPI + Jinja2/HTMX
  ├─ auth / sessions / CSRF
  ├─ drafts / tickets / admin
  └─ jobs в PostgreSQL
        │
        ▼
worker
  ├─ ai_check (Claude Code)
  ├─ compose_news (Claude Code + WebFetch)
  ├─ generate_image (ProxyAPI)
  └─ publish_vk / publish_telegram
        │
        ▼
PostgreSQL + var/media + var/jobs
```

**Стек:** Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL,
Jinja2, Tailwind (собранный CSS), Argon2id, Claude Code CLI, ProxyAPI (Flux / GPT Image).

**Граница безопасности:** Claude Code читает и правит JSON, но не публикует. Публикацию
выполняет детерминированный Python-код после действия пользователя или админа.

---

## Локальный запуск

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
# заполнить DATABASE_URL, ADM_PASSW, ключи VK/TG/ProxyAPI
alembic upgrade head
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
```

Открыть `http://127.0.0.1:8000/login`.

В dev-режиме `WORKER_INPROCESS=true`: очередь задач обрабатывается внутри веб-приложения.
На VPS `WORKER_INPROCESS=false` и отдельный systemd-юнит `python -m webapp.worker`.

Для AI-задач нужен авторизованный Claude Code. Локально можно использовать текущую сессию
(`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`), на сервере — `CLAUDE_CODE_OAUTH_TOKEN`
из `claude setup-token`.

---

## Деплой на Linux-сервер

Репозиторий рассчитан на развёртывание по проектному скиллу
[`.claude/skills/rompetr-crm/SKILL.md`](.claude/skills/rompetr-crm/SKILL.md). Скилл
подхватывается Claude Code автоматически и содержит проверенную последовательность
для Debian 12: пакеты, пользователи, venv, PostgreSQL, systemd, nginx, TLS, worker
и типовые ловушки. Хронология реального деплоя — в `docs/DEPLOY-JOURNAL.md`.

Коротко:

1. Debian 12, Python 3.11+, PostgreSQL, nginx, systemd, git.
2. Пользователи `cpapp` (web), `cpworker` (worker), группа `cpmedia`; код в
   `/srv/rompetr/crm`, venv в `/srv/rompetr/venv`.
3. Секреты — в `/etc/rompetr-crm/app.env` (640 `root:cpapp`), каталог 750 `root:cpapp`;
   в git файл не попадает.
4. `python -m alembic upgrade head` под пользователем приложения.
5. systemd-юниты `rompetr-web` (uvicorn на `127.0.0.1:8000`) и `rompetr-worker`;
   nginx как reverse proxy; UFW 22/80/443; TLS через certbot.
6. Проверка: `/healthz`, `/login`, вход админом, AI-проверка черновика.

Docker не требуется. Для AI-задач нужен Claude Code CLI, доступный сервисному
пользователю, и переменные `ANTHROPIC_*`/`CLAUDE_*` в `app.env`. Если на сервере
есть отдельный исходящий IP, задайте `CLAUDE_HTTP_PROXY` — прокси применится только
к процессу Claude Code.

---

## Структура репозитория

```text
webapp/            FastAPI-приложение, модели, сервисы, шаблоны
alembic/           миграции БД
scripts/           git_guard, json_to_md, smoke_publish, init_db, восстановление PG
tests/             pytest: auth, черновики, публикация, очередь, compose
docs/              план и журнал деплоя
.claude/           субагенты Checker/Pixly, команда publish, настройки worker
bot.py             legacy-публикатор Telegram
posts/             данные постов (в git не попадают)
```

Данные и секреты не коммитятся: `posts/`, `var/`, `*.png`, `.env`, профиль Chrome,
сторонний `.mcp-servers/` исключены через `.gitignore` и проверяются
`scripts/git_guard.py`.

---

## Безопасность

- Репозиторий публичный: любой секрет в истории считается скомпрометированным.
- Перед push выполняется `python -I scripts/git_guard.py --tracked`.
- `.env` и legacy-файлы с токенами не попадают в git.
- Пароли — Argon2id; сессии в БД; CSRF на всех не-GET; rate limit на вход/регистрацию.
- Админ ID 0 защищён CHECK-ограничением, триггером и partial unique index.
- Медиа отдаётся только автору и админу.

---

## Перспективы

- Домен `rompetr.ru` и TLS-сертификат; пока приложение доступно по IP.
- Бэкапы PostgreSQL и медиа на VPS.
- Роль `moderator` и разделение редактора и администратора.
- HTMX-обновления без перезагрузки страницы.
- SMTP-провайдер для реальных писем подтверждения.
- Автоматическое обновление статуса задач.
- Импорт старых постов и миграция legacy-пайплайна.
- Публикация на любые темы, а не только DEX/DeFi.
- Аналитика публикаций, расход API, отчёты по каналам.
- Платный X API как альтернатива ручной очереди.
- Мультипользовательские рабочие пространства и биллинг.

---

## Документация

- `docs/CRM-PLAN.md` — план и чек-лист этапов.
- `docs/DEPLOY-JOURNAL.md` — хронология решений и чек-лист деплоя на VPS.
- `.claude/plans/crm-web-platform.yaml` — машинная спецификация.
- `.claude/skills/rompetr-crm/SKILL.md` — скилл для Claude Code: структура, запуск, правки, проверки и публикация.
- `docs/CLAUDE-CODE-DEEPSEEK-SETUP.md` — переход Claude Code на API DeepSeek на Windows 10.
- `PIPELINE.md`, `PUBLISH-COMMAND.md` — старый конвейер Content Plant.

---

## Статус

CRM развёрнута на VPS Debian 12: systemd-юниты `rompetr-web` и `rompetr-worker`,
nginx, PostgreSQL, UFW и fail2ban. Публичный адрес этапа — `http://62.171.228.41`;
вход админом и `/admin` проверены. Локально: 47 автотестов, `ruff`, миграции,
ручные сценарии входа, черновиков, AI-перевода, изображений и публикаций.

Следующие шаги: переключить домен и выпустить TLS, добавить
`CLAUDE_CODE_OAUTH_TOKEN` для AI-задач, настроить SMTP и бэкапы.
