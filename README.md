# rompetr-crm

CRM для подготовки и публикации новостей в соцсети. Работает поверх существующего
конвейера Content Plant: JSON-посты, Checker, Pixly, публикация в VK и Telegram.

## Что уже есть в репозитории

- `PIPELINE.md`, `PUBLISH-COMMAND.md`, `PUBLICATIONS.md` — описание текущего конвейера и журнал.
- `.claude/agents/` — субагенты Checker, Pixly и gitpublisher.
- `bot.py` — legacy-публикатор Telegram (будет обёрткой над `webapp.services.telegram`).
- `webapp/` — веб-приложение (FastAPI + Jinja2/HTMX), появляется на этапах 1–5.

## Что не попадает в git

`posts/`, `var/`, все изображения, `.env`, профиль Chrome
`.chrome-x-profile/`, сторонний `.mcp-servers/`, виртуальные окружения и кэши.
Политику проверяет `scripts/git_guard.py` и pre-commit hook.

## Локальный запуск (после этапа 1)

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -r requirements-dev.txt
cp .env.example .env          # заполнить значения
alembic upgrade head
uvicorn webapp.main:app --reload
```

## Документация

- Человекочитаемый план и чек-лист: `docs/CRM-PLAN.md`
- Машинная спецификация: `.claude/plans/crm-web-platform.yaml`

## Безопасность

Репозиторий публичный. Любой секрет, попавший в историю, считается
скомпрометированным. Перед первым push ротируйте VK, Telegram и ProxyAPI ключи.
