---
name: rompetr-crm
description: Работа с репозиторием rompetr-crm: структура проекта, запуск FastAPI и worker, миграции PostgreSQL, правки моделей/сервисов/шаблонов, тесты и ruff, обновление README и подготовка к публикации в GitHub. Используй при любой задаче в C:\Users\rp\course\content.
---

# rompetr-crm — как работать с проектом

## 1. Что это

FastAPI-приложение для подготовки и публикации новостей «Разум DEX». Стек:
FastAPI + Jinja2/HTMX, PostgreSQL, SQLAlchemy 2 + Alembic, Pydantic v2,
Argon2id, очередь `jobs`, worker с Claude Code CLI и ProxyAPI.

Главное правило: **Claude Code не публикует в соцсети**. Публикацию выполняет
детерминированный Python-код (`webapp/services/publish.py`) после действия
пользователя или админа.

## 2. Карта репозитория

```text
webapp/
  main.py            сборка FastAPI, lifespan, in-process worker
  config.py          pydantic-settings, все переменные .env
  db.py              engine, SessionLocal, Base
  models/            users, posts, jobs, publications, audit, tickets
  schemas/           post_document.py — схема поста и лимиты площадок
  services/          auth, posts, media, publish, telegram, vk, images,
                     jobs, claude_runner, scheduler, bootstrap
  routers/           public, auth, dashboard, drafts, tickets, admin, media
  templates/         Jinja2: base, auth, drafts, admin, dashboard
  static/            CSS и внешние JS (CSP: только self)
  worker.py          цикл обработки jobs
alembic/versions/    миграции; новые схемы только через Alembic
scripts/             git_guard, json_to_md, smoke_publish, init_db,
                     pg_recover, check_keys, install_hooks
tests/               pytest: auth, drafts, publish, jobs, compose, guard
docs/                CRM-PLAN.md, DEPLOY-JOURNAL.md
.claude/             скиллы, субагенты, команды, планы
posts/               данные постов (в git не попадают)
var/                 media, jobs, logs, mail, backups (в git не попадают)
```

## 3. Быстрый старт

```powershell
cd C:\Users\rp\course\content
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
```

- Вход: `http://127.0.0.1:8000/login`.
- Если порт занят старым процессом, сначала остановить его:
  `Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`.
- Сервер в фоне может быть остановлен защитой от нехватки памяти. Не запускать
  без просьбы пользователя; сообщить причину и дать команду.

### Worker

- Dev: `WORKER_INPROCESS=true` — очередь обрабатывается потоком внутри FastAPI.
- VPS: `WORKER_INPROCESS=false` + отдельный `python -m webapp.worker`.
- Разовая задача: `python -m webapp.worker --once`.
- Логи задач: `var/jobs/<job>.out.log` и `.err.log`, `/admin/jobs`.

### База и миграции

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic revision -m "change name"
```

Новое поле модели = миграция + обновление формы/сервиса/теста. Не менять схему
только в модели.

## 4. Как вносить изменения

- **Модель:** `webapp/models/*.py`, затем миграция в `alembic/versions/`.
- **Бизнес-логика:** `webapp/services/*.py`. Роутер не должен содержать длинную логику.
- **HTTP-маршрут:** `webapp/routers/*.py`; CSRF-зависимость уже на роутерах.
- **Шаблон:** `webapp/templates/...`; JS только внешними файлами в `webapp/static/js/`
  из-за CSP `script-src 'self'`.
- **Тест:** `tests/test_*.py`. Для новых веток — минимальный тест на поведение.
- **Права:** admin — модерация и публикация; user — свои черновики; guest — без публикации.

Чекбоксы площадок и `image_prompt` хранятся в `posts.platforms_enabled` и
`posts.image_enabled`. Выключенное поле не участвует в проверке, AI-переводе и
публикации, но загруженная картинка всё равно прикрепляется к Telegram.

## 5. Проверки перед коммитом

```powershell
.venv\Scripts\python.exe -m ruff check webapp tests scripts
.venv\Scripts\python.exe -m pytest -q -p no:warnings
python -I scripts/git_guard.py --staged
git status --short
```

- Guard: 0 — чисто; 2 — запрещённый путь; 3 — секрет; 4 — размер.
- Не коммитить `posts/`, `var/`, `.env`, `*.png`, `.mcp-servers/`.
- Репозиторий публичный: любой секрет в истории считается скомпрометированным.

## 6. README и документация

Обновлять README, если меняются:

- назначение или список возможностей;
- стек, архитектура, способ запуска;
- переменные `.env` или режимы worker;
- публичные команды и скрипты;
- перспективы/статус.

Стиль README: по-русски, короткие разделы, таблица болей клиентов, команды в блоках,
без внутренних путей вида `C:\Users\rp\.cache` и без секретов.

После значимых изменений добавлять запись в `docs/DEPLOY-JOURNAL.md`: что сделано,
где файлы, что проверить на VPS, новые ловушки.

## 7. Подготовка к публикации

1. `ruff` и `pytest` зелёные.
2. `python -I scripts/git_guard.py --tracked` → 0.
3. README актуален; журнал дополнен.
4. `git add` только конкретные системные пути, никогда `git add -A`.
5. Коммит с трейлером `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
6. `git push origin main`.
7. После push проверить, что в репозитории нет `posts/`, `var/`, `.env`.

Remote: `https://github.com/RomPetr/rompetr-crm` (публичный, ветка `main`).
Субагент `gitpublisher` предназначен для коммитов/пушей только системных файлов.

## 8. Диагностика

| Симптом | Что проверить |
|---|---|
| Порт 8000 занят / страница не открывается | `Get-NetTCPConnection -LocalPort 8000`; старый uvicorn держит порт |
| `WinError 10048` | остановить старый процесс, дождаться освобождения порта |
| Worker не берёт задачи | `WORKER_INPROCESS`, `/admin/jobs`, `var/logs/uvicorn-8000.log` |
| `Claude Code exit 1` | `var/jobs/<job>.err.log`; чаще всего авторизация или недоступная модель |
| `unrecognized_model` | это предупреждение stderr; смотреть JSON-результат CLI |
| `claude-haiku-5-5` / `claude-opus-5-5` | задать доступный `CLAUDE_MODEL`, fallback только вместе с моделью |
| Telegram без картинки | есть ли primary asset; `image_enabled` на публикацию не влияет |
| VK `error 27` | групповой токен не умеет `photos.*`; публикуется только текст |
| X не публикуется автоматически | ручная очередь; кнопка «Открыть X с картинкой» использует локальный Chrome |
| Ошибки проверки после ввода | сохранить черновик; проверка идёт по сохранённой версии |
| Память | не запускать фоновый сервер без просьбы; сообщить причину остановки |

## 9. Запреты

- Не публиковать в соцсети от имени агента без явной команды пользователя.
- Не менять `.env` и не печатать значения токенов.
- Не добавлять в git `posts/`, медиа, `var/`, `.env`, профиль Chrome.
- Не отключать Checker и не обходить валидатор лимитов ради «быстрого» поста.
- Не редактировать чужие посты напрямую в БД вместо UI, если есть маршрут.
