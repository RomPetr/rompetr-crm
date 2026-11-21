# Журнал разработки и деплоя CRM

**Назначение:** восстановить цепь событий и понять, что и где исправить при переносе на VPS.
**Формат:** новые записи добавляются в конец хронологии. Блоки `[VPS]` — приоритетные действия на сервере.
**Время:** локальное UTC+8. Репозиторий: `C:\Users\rp\course\content`.

---

## 1. Чек-лист деплоя на VPS (держать в актуальном состоянии)

> **Историческая часть.** Это первоначальный план. Фактические отличия: PostgreSQL 15,
> домен `rompetr.autos`, AI через DeepSeek (без OAuth), TLS ожидает сертификат
> провайдера. Актуальное состояние — в записях ниже и в README.

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

### 2026-11-16 13:40 — исправлена авторизация worker’а

- Ошибка AI-проверки: `Claude Code exit 1` с пустым stderr. В JSON-ответе CLI было `Not logged in`.
- Причина: uvicorn запускается из PowerShell, где нет `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`; переменные есть только в окружении сессии Claude Code.
- Исправление: settings получили поля `ANTHROPIC_AUTH_TOKEN` и `ANTHROPIC_BASE_URL`; runner берёт их из `.env`. Если задан `CLAUDE_CODE_OAUTH_TOKEN`, используется он, а локальный токен не передаётся.
- `CLAUDE_MODEL` очищен локально: при пустом значении runner не добавляет `--model` и `--fallback-model`, CLI использует модель по умолчанию. На VPS задать `CLAUDE_MODEL=sonnet`.
- [VPS] В `app.env` достаточно `CLAUDE_CODE_OAUTH_TOKEN` из `claude setup-token`. `ANTHROPIC_AUTH_TOKEN` на сервер не переносить.

### 2026-11-16 14:05 — индикация ожидания задачи

- После постановки AI-проверки или генерации PNG страница показывает блок «Задача #N в работе»: спиннер, таймер секунд, статус и кнопку «Обновить страницу».
- Через 90 секунд появляется подсказка проверить `/admin/jobs`.
- По завершении после обновления показывается «завершена» или текст ошибки.
- Обнаружен и исправлен побочный баг: `publisher.js` был вставлен внутрь блока `<title>`, из-за чего не загружался. Теперь оба скрипта подключены в конце content-блока.
- Следующий шаг: автоматическое обновление статуса без ручного refresh (HTMX или polling endpoint).

### 2026-11-16 14:40 — повторная генерация картинки

- Симптом: после нажатия «Сгенерировать PNG» страница сразу показывала «Задача #2 завершена», нового изображения не появлялось.
- Причина: ключ идемпотентности `post + hash(image_prompt)` возвращал старую успешную задачу #2. Файл от неё лежал в `var/media`, но ассет был удалён через UI.
- Исправление: для `generate_image` дедупликация только по активным задачам (`queued`/`running`); после успеха каждый клик создаёт новую задачу с уникальным ключом. Для `ai_check` проваленная задача переиспользуется (requeue), а не вызывает конфликт уникального ключа.
- Ошибки `claude -p` теперь содержат текст из JSON-ответа (`Not logged in`) и путь к логу.
- Осиротевшие файлы удалённых ассетов пока не чистятся; это отдельная задача уборки медиа.

### 2026-11-16 14:55 — скачивание изображения

- Рядом с «Удалить изображение» добавлена кнопка **«Сохранить изображение»**.
- Новый маршрут `GET /drafts/{post}/assets/{asset}/download` отдаёт PNG как attachment с именем `<base_slug>-image-<id>.png`.
- Доступ проверяется так же, как к странице черновика: автор или админ.

### 2026-11-16 15:10 — выбор модели и автоперезагрузка

- В форме генерации PNG появился выбор модели: `black-forest-labs/flux.2-pro` или `gpt-image-1-mini`. Выбор уходит в payload задачи и используется первым; вторая модель остаётся резервом.
- Кнопки постановки задач переименованы в **«Запустить»**.
- Пока задача `queued`/`running`, страница опрашивает `GET /drafts/{post}/jobs/{job}/status` каждые 2 секунды и перезагружается автоматически при завершении. Ручная кнопка осталась как резерв.
- CSP: запросы разрешены через `connect-src 'self'`.

### 2026-11-16 15:20 — Этап 6: локальная обкатка

- `ruff` — чисто. `pytest` — 25 тестов, общее покрытие 70%.
- Критические модули: auth 86%, publish 94%, validator 82%, jobs 72%.
- `scripts/git_guard.py --tracked` — код 0, 107 отслеживаемых файлов, без медиа и секретов.
- `pg_dump -Fc` создан: `var/backups/stage6.dump` (58 133 байта), `pg_restore -l` — 129 записей, таблица `users` присутствует.
- Полный restore в отдельную БД не выполнен: роль `rompetr_app` без `CREATEDB`, нужен пароль `postgres`.
- [VPS] Проверка restore: `createdb -U postgres rompetr_restore`, затем `pg_restore -U postgres -d rompetr_restore --no-owner var/backups/<dump>` и вход в восстановленную БД.
- Ручной сценарий: вход, регистрация, черновик, загрузка и генерация картинки проверены пользователем. Публикация из веб-интерфейса в реальные каналы не выполнялась — маршрут покрыт тестами с mock.

### 2026-11-16 22:10 — флаги площадок и AI-перевод

- В форме черновика у каждого текста и у `image_prompt` появился чекбокс «Включить». Снятый флаг исключает поле из валидации, AI-перевода и публикации.
- Миграция `c3e06824bb4a`: колонки `posts.platforms_enabled` (JSON) и `posts.image_enabled` (bool). Существующие посты получили все площадки включёнными.
- «AI-проверка» переименована в **«AI-перевод»**: агент переводит включённые тексты на русский, X оставляет английским, чинит формулировки и возвращает JSON; страница обновляется автоматически.
- Для админа и будущей роли `moderator` кнопка «На проверку» скрыта. Роль `moderator` пока не добавлена в constraint и UI.
- Публикация пропускает выключенные площадки; если выключен `image_prompt`, картинка не прикрепляется к Telegram.
- Тесты: 31 зелёный, `ruff` чистый.

### 2026-11-16 22:35 — метки AI-перевода и правок

- Сообщение о завершении исправлено: «AI-перевод и проверка выполнены»; для картинки — «генерация изображения выполнена».
- Worker сравнивает тексты до/после AI: если в старом тексте не было кириллицы, а в новом есть — `translated`; иначе `fixed`. Результат сохраняется в `jobs.payload.result.changes`.
- На странице черновика над изменённым полем появляется зелёная метка «Переведено» или «Исправлено», поле подсвечивается рамкой. Метки живут до следующего сохранения (проверка по `post_version`).
- Чекбоксы выровнены по правому краю в заголовках полей.
- Тесты: 32 зелёных, `ruff` чистый. Задача #9 была обработана до включения сравнения, поэтому меток у неё нет — нужен новый запуск AI-перевода.

### 2026-11-16 22:45 — VK без обязательных хэштегов

- Убрана проверка «3–7 хэштегов» для VK в валидаторе, Checker, SKILL, PIPELINE и подписи поля.
- Хэштеги в VK теперь необязательны; лимит 700–1500 символов с учётом ссылки сохранён.
- Instagram, TikTok и X не тронуты.
- Тесты: 32 зелёных, `ruff` чистый; сервер перезапущен.

### 2026-11-16 23:00 — картинка публикуется всегда

- Причина публикации TG без фото: у поста 4 был выключен `image_prompt`; публикатор уважал флаг. Теперь наличие ассета важнее флага: если картинка загружена, она всегда прикрепляется к Telegram, независимо от `image_prompt`.
- `image_prompt` влияет только на AI-перевод/генерацию, но не на публикацию существующего файла.
- Уже опубликованное сообщение `t.me/defidexmind/20` исправлено через `editMessageMedia`: текст заменён на фото с той же подписью, ссылка и message_id сохранены.
- Добавлен тест: ассет при выключенном `image_prompt` всё равно уходит в Telegram.

### 2026-11-16 23:20 — генерация новости из CRM

- На странице черновика под админом появилась карточка **«Сгенерировать новость»** с выбором модели изображения.
- Новая задача `compose_news`: Claude получает доступ к WebFetch/WebSearch, читает RSS пяти источников, выбирает свежую новость, открывает статью и пишет JSON.
- Worker валидирует JSON, заполняет `source.title/url/publisher/published_at`, все тексты площадок и `image_prompt`, включает площадки, затем генерирует картинку выбранной моделью.
- После успеха страница обновляется и сверху показывается зелёная плашка **ГОТОВО**. Ошибки видны в `/admin/jobs` и в блоке задачи.
- Тесты: 35 зелёных, `ruff` чистый; добавлен bootstrap админа в тестовом fixture и изоляция очереди между тестами.
- [VPS] Для compose_news нужен доступ WebFetch из сети VPS; при блокировке источников задача упадёт с логом.

### 2026-11-17 — ошибка fallback-модели

- Задача #11 `compose_news` упала: `There's an issue with the selected model (claude-haiku-5-5)`.
- Причина: `CLAUDE_FALLBACK_MODEL=haiku` передавался даже без основной модели; CLI разворачивал алиас в недоступную `claude-haiku-5-5`.
- Исправление: fallback добавляется только вместе с явным `CLAUDE_MODEL`; локальный fallback очищен. Проверка `claude -p` вернула exit 0.
- [VPS] `CLAUDE_FALLBACK_MODEL` задавать только если модель реально доступна в плане.

### 2026-11-17 — явная модель для worker’а

- После удаления fallback CLI стал выбирать модель по умолчанию — `claude-opus-5-5`, недоступную в окружении.
- Локально в `.env` задан явный `CLAUDE_MODEL=deepseek-v4.1-flash:cloud` (значение из переменных окружения Claude Code).
- Проверка runner в чистом окружении без `ANTHROPIC_DEFAULT_*`: exit 0, результат OK.
- [VPS] В `app.env` задать `CLAUDE_MODEL` доступной моделью (например `sonnet`), иначе CLI выберет модель плана по умолчанию.

### 2026-11-17 — публикация админом сразу после проверки

- Если у админа проверка черновика проходит без ошибок, на странице появляется карточка «Публикация» с кнопкой «Опубликовать» даже без отдельного одобрения.
- Маршрут публикации для админа валидирует пост, фиксирует одобрение (`approved_by=0`) и сразу публикует. Для `user` по-прежнему нужен статус approved, `guest` — запрещено.
- Тесты: 36 зелёных, `ruff` чистый.

### 2026-11-17 — защита от повторной публикации

- Для статуса `published` карточка публикации показывает «Опубликовано. Повторная публикация отключена.» и неактивную кнопку.
- Маршрут `POST /drafts/{id}/publish` для уже опубликованного поста отвечает 400, поэтому двойной клик и повторный POST не создают дублей.
- Тесты: 36 зелёных, `ruff` чистый; сервер перезапущен.

### 2026-11-17 — compose_news retry и отображение ошибки

- Задача #13 завершилась успешно с третьей попытки: пост 6 заполнен новостью CoinDesk о Lighter, картинка сгенерирована (asset 9), страница показывает ГОТОВО.
- Ошибка `unrecognized_model` была предупреждением stderr предыдущей попытки и висела в UI во время retry.
- Исправлено: для `queued`/`running` колонка ошибки показывает «—»; текст ошибки берётся из JSON-результата CLI, а не из stderr-предупреждения.
- Тесты: 37 зелёных, `ruff` чистый; сервер перезапущен.

### 2026-11-17 — проверка черновика с несохранёнными полями

- Кнопка «Проверить» теперь отправляет основную форму черновика, а не пустую служебную.
- Если введённые значения отличаются от сохранённых, страница показывает «Сначала сохраните черновик, затем проверьте», сохраняя весь введённый текст и состояние чекбоксов.
- Проверка выполняется только по сохранённой версии; после «Сохранить» она проходит как раньше.
- Тесты: 38 зелёных, `ruff` чистый; сервер перезапущен.

### 2026-11-17 — публичный GitHub

- Создан публичный репозиторий: https://github.com/RomPetr/rompetr-crm (ветка `main`).
- Первый push выполнен, 112 файлов; `posts/`, `var/`, `.env`, `.mcp-servers/` не попали.
- GitHub secret scanning и push protection включены.
- README переписан под публичный проект: цели, боли клиентов, возможности, архитектура, запуск, безопасность, перспективы.
- Ключи VK/TG/ProxyAPI не ротировались по решению пользователя; в git они не попадают. При компрометации заменить.

### 2026-11-17 — деплой на VPS по IP

- Сервер: **62.171.228.41**, Debian 12, 2 vCPU, 6 ГБ RAM, 40 ГБ SSD, пользователь `rp` + sudo.
- Установлены Python 3.11, PostgreSQL 15 (штатная версия Debian 12; в плане был 16), nginx, certbot, UFW, fail2ban, git.
- Созданы `cpapp`, `cpworker`, группа `cpmedia`; код в `/srv/rompetr/crm`, venv `/srv/rompetr/venv`.
- `.env` в `/etc/rompetr-crm/app.env`: `APP_ENV=dev`, `APP_BASE_URL=http://62.171.228.41`, `COOKIE_SECURE=false`, `WORKER_INPROCESS=false`, локальные ключи VK/TG/ProxyAPI, `CLAUDE_MODEL=sonnet`.
- Миграции Alembic применены: 14 таблиц, админ ID 0 создан, роль active.
- systemd: `rompetr-web` и `rompetr-worker` — active; nginx проксирует порт 80 на 127.0.0.1:8000.
- UFW: 22/80/443; fail2ban активен.
- Проверено публично: `http://62.171.228.41/healthz` → 200, `/login` → 200, вход admin и `/admin` → 200.

Ловушки, исправленные при деплое:

- `/etc/rompetr-crm` был 750 root:root — `cpapp` не читал env. Исправлено на 750 root:cpapp, файл 640.
- `.env` скопировался с CRLF, pydantic не парсил булевы значения. Исправлено `sed -i 's/
$//'`.
- После замены `sites-enabled/default` nginx не перезагрузился: нужен `systemctl reload nginx`, одного `enable --now` недостаточно.

### 2026-11-18 — AI-переменные и Claude CLI для worker

- Из локального `.env` на VPS перенесены `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`,
  `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`,
  `ANTHROPIC_DEFAULT_HAIKU_MODEL`; значения не печатались и в git не попадали.
- Claude Code CLI 2.1.325 скопирован из установки `rp` в `/usr/local/bin/claude`
  (349 МБ), чтобы его мог запускать `cpworker`.
- Создан `CLAUDE_CONFIG_DIR=/var/lib/rompetr/claude` (cpworker:cpworker, 700);
  `HOME=/var/lib/rompetr`; `CLAUDE_BIN=/usr/local/bin/claude`.
- `CLAUDE_CODE_OAUTH_TOKEN` и `CLAUDE_FALLBACK_MODEL` оставлены пустыми —
  worker авторизуется через `ANTHROPIC_AUTH_TOKEN` и Anthropic-совместимый endpoint.
- **Важно:** DeepSeek API отклоняет локальный алиас `deepseek-v4.1-flash:cloud`
  с ошибкой 400 «supported API model names are deepseek-flash, deepseek-v4-pro».
  На VPS выставлены `CLAUDE_MODEL=deepseek-flash` и такие же значения в
  `ANTHROPIC_DEFAULT_*`.
- Проверка `claude_runner.run("Reply with exactly OK")` от `cpworker`: exit 0,
  `result: OK`; предупреждение `[claude-code:unrecognized_model]` в stderr безвредно.
- `rompetr-web` и `rompetr-worker` перезапущены, оба active; worker получил
  `HOME`, `CLAUDE_BIN`, `CLAUDE_CONFIG_DIR`, `CLAUDE_MODEL`, `ANTHROPIC_BASE_URL`
  и токен.
- Обновление CLI: `install -m 0755 <новый бинарник> /usr/local/bin/claude`
  (обновление под `rp` не заменит системную копию).

### 2026-11-18 — Claude Code через второй IP (gost)

- `gost-claude.service` (enabled, active) слушает `127.0.0.1:3128` и выпускает
  соединения через дополнительный адрес `62.171.228.183`:
  `/usr/bin/gost -L "http://127.0.0.1:3128?interface=62.171.228.183"`.
- В приложение добавлена настройка `CLAUDE_HTTP_PROXY`; `claude_runner` подставляет
  `HTTP_PROXY`/`HTTPS_PROXY` (в верхнем и нижнем регистре) и `NO_PROXY=127.0.0.1,localhost,::1`
  **только в окружение процесса Claude Code**, не затрагивая остальной трафик worker’а.
- В `/etc/rompetr-crm/app.env` добавлено `CLAUDE_HTTP_PROXY=http://127.0.0.1:3128`.
- Проверка egress: прямой `curl` → `62.171.228.41`, через прокси → `62.171.228.183`.
- Проверка, что CLI действительно использует прокси: с мёртвым прокси
  (`127.0.0.1:9`) запуск завершился таймаутом, с gost — `exit 0`, `result: OK`.
- `gost-claude`, `rompetr-worker`, `rompetr-web` — active; worker получил
  `CLAUDE_HTTP_PROXY`; `/healthz` → 200.

### 2026-11-18 — проверка AI-проверки на VPS

- Через интерфейс CRM создан тестовый черновик #1 и запущена AI-проверка.
- Задача `ai_check` #1 завершилась со статусом `succeeded`.
- Telegram: английский текст 810 символов переведён на русский, 868 символов,
  ссылка `https://www.theblock.co/` сохранена последней строкой.
- X: остался на английском, 187 символов, без изменений.
- На странице черновика появилась метка «Переведено», ошибок нет.
- Черновик оставлен для визуальной проверки: http://62.171.228.41/drafts/1

### 2026-11-18 — compose_news: бюджет, субагенты и черновик #2

- Кнопка «Сгенерировать новость» в черновике #2 создала задачу #2, но она трижды
  завершилась с `budget_exhausted` при лимите `$2` и 14 ходах.
- При этом модель успела записать валидный `post.json` (7,2 КБ): все лимиты площадок
  проходили, Telegram/VK/Instagram/TikTok были на русском, X на английском. JSON не был
  применён к посту, поэтому новость не отобразилась.
- Исправлено: `CLAUDE_COMPOSE_BUDGET_USD=6`, `CLAUDE_COMPOSE_MAX_TURNS=30`,
  субагенты `Task`/`Agent` запрещены, в промпте запрещены субагенты и Bash;
  `compose_news` теперь имеет `max_attempts=1`, чтобы не тратить бюджет на автоповторы.
- Повторный запуск из UI: задача #3 — `succeeded` за 148 секунд, `$1.81`, 10 ходов,
  0 субагентов. Черновик #2 заполнен, PNG 1,44 МБ создан, метка «ГОТОВО» показывается
  при `?job=3`; X остался английским, остальные площадки — на русском.

### 2026-11-18 — правило X: 0–1 хэштег

- Для X закреплено правило: по умолчанию 0 хэштегов, максимум 1 и только для
  конкретного события/кампании. Общие `#crypto`, `#DeFi`, `#DEX`, `#AIagents`
  не добавляются; для конкретной монеты используется cashtag `$BTC`/`$XRP`.
- Правило прописано в `.claude/skills/ai-news-to-social/SKILL.md`,
  `.claude/agents/checker.md`, `PIPELINE.md`, `PUBLISH-COMMAND.md`,
  `.claude/commands/publish.md` и в промпте `compose_news` (`webapp/worker.py`).
- Из всех X-примеров скилла убраны хэштеги; примеры VK/Instagram/TikTok не менялись.

### 2026-11-18 — гостевые квоты и счётчики на /drafts/n

- Гость может один раз запустить «Сгенерировать новость» (`compose_news`) и два раза
  «Сгенерировать PNG» (`generate_image`) суммарно по всем своим черновикам.
  Лимиты задаются `GUEST_COMPOSE_LIMIT=1` и `GUEST_IMAGE_LIMIT=2`.
- Квота считается по задачам со статусами `queued`/`running`/`succeeded`; неудачные
  попытки её не съедают. Активная задача не создаёт дубль.
- На карточках `/drafts/n` рядом с кнопками появились счётчики: «Поиск: X/1»,
  «Картинки: Y/2» и «Публикаций: N». Для админа поиск/картинки показываются по посту,
  для гостя — по пользователю.
- Гость видит карточку «Публикация» с заблокированной кнопкой и счётчиком публикаций;
  публиковать по-прежнему может только админ или автор после одобрения.
- Добавлены `webapp/services/usage.py` и тест `tests/test_guest_quotas.py`.
- На `/admin/users` у гостя видны использование и эффективные лимиты, кнопки
  «+1 поиск» и «+1 картинка» увеличивают персональные лимиты
  (`users.guest_compose_limit`, `users.guest_image_limit`; миграция
  `7b2f4c9d1a6e`). Если персональный лимит не задан, действует глобальный.
- Всего 41 тест, `ruff` чистый; миграция применена локально.

### 2026-11-18 — контроль длины после перевода

- Причина ошибки «telegram: 1059 символов, нужно 800–1024»: `ai_check` переводил текст,
  но не проверял длину после перевода, а `run_ai_check` применял результат без
  финальной валидации.
- В `_check_prompt` добавлены явные лимиты всех площадок и требование пересчитывать
  длину уже после перевода; при превышении Telegram 1024 символов Checker обязан
  сокращать текст, сохраняя факты и цифры.
- `run_ai_check` теперь вызывает `validate_document` и не применяет JSON с выходом
  за лимиты; задача завершается ошибкой, черновик остаётся прежним.
- В `.claude/agents/checker.md` добавлен обязательный раздел о финальной проверке
  длины после каждого изменения.
- Добавлен тест на отклонение Telegram длиннее 1024; всего 42 теста, `ruff` чистый.

### 2026-11-18 — новая генерация картинки не становилась основной

- Симптом: job #8 (`flux.2-pro`) завершилась успешно, PNG сохранился, но в черновике
  #5 осталась старая картинка от `gpt-image-1-mini`.
- Причина: `media.save_bytes` ставил `is_primary=True` только первому ассету поста,
  поэтому все последующие генерации сохранялись как неосновные.
- Исправлено: каждый новый (или повторно загруженный) ассет становится primary,
  остальные переводятся в `is_primary=false`.
- Миграция `d4e8a1b2c3f5` выставляет primary самый новый ассет для каждого поста,
  включая уже созданные записи.
- Файлы картинок лежат в `/srv/rompetr/crm/var/media/posts/<post.public_id>/<sha256[:20]>.png`.
- Добавлен тест на смену primary; всего 43 теста, `ruff` чистый.

### 2026-11-18 — модерация на странице черновика

- Для администратора на `/drafts/n` добавлена карточка «Модерация» в том же формате,
  что и остальные области: кнопка «Одобрить» и форма «Отклонить» с полем причины.
- Маршруты `POST /drafts/{id}/approve` и `POST /drafts/{id}/reject` используют те же
  `posts.approve`/`posts.reject`, что и кнопки «Подтвердить»/«Отклонить» в `/drafts`,
  пишут audit log и возвращают на тот же черновик.
- Модерация доступна только админу; опубликованный пост модерировать нельзя.
  Пустая причина отклонения возвращает на страницу с ошибкой.
- Добавлены тесты `tests/test_draft_moderation.py`; всего 45 тестов, `ruff` чистый.

### 2026-11-18 — гостевая публикация и управление лимитами

- Гостю разрешена одна публикация: только после одобрения администратором и при
  положительном остатке лимита. Квота считается по опубликованным постам автора.
- Текст на `/drafts/n`: «Гостевой доступ: публикация возможна после одобрения
  администратором и при положительном лимите публикаций.» Кнопка активна только для
  `approved`-поста и при остатке квоты.
- Добавлен `GUEST_PUBLICATION_LIMIT=1` и персональное поле
  `users.guest_publication_limit` (миграция `f6a1b2c3d4e5`).
- На `/admin/users` вместо кнопок «+1» — форма с тремя числами: поиск, картинки,
  публикации. Она задаёт персональные лимиты гостя; audit log фиксирует изменение.
- Добавлены тесты на публикацию гостем и на форму лимитов; всего 46 тестов,
  `ruff` чистый.

### 2026-11-18 — подпись модерации для опубликованного поста

- Опубликованный пост показывал «Модерация: отклонено», потому что шаблон считал
  одобренным только статус `approved`.
- Теперь статусы `approved` и `published` показывают «Модерация пройдена»;
  «Модерация: отклонено» остаётся только для отклонённых/неодобренных.
- Добавлен тест на подпись published-поста; всего 47 тестов, `ruff` чистый.

### 2026-11-18 — домен rompetr.autos и DCV

- DNS `rompetr.autos` и `www.rompetr.autos` указывает на `62.171.228.41`.
- nginx: `server_name 62.171.228.41 rompetr.autos www.rompetr.autos`; домен и
  `www` отдают `/healthz` и `/login` — 200.
- DCV-файл провайдера опубликован в
  `/srv/rompetr/dcv/.well-known/pki-validation/` и доступен по HTTP на apex и www
  с точным содержимым (99 байт). CSR проверен, CN `rompetr.autos`; копия лежит в
  `/etc/nginx/ssl/rompetr.autos.csr`.
- `APP_BASE_URL` переключён на `http://rompetr.autos`; web перезапущен.
- HTTPS ещё не включён: нужны выданные провайдером файлы сертификата и приватного
  ключа. После их получения: `APP_ENV=prod`, `APP_BASE_URL=https://rompetr.autos`,
  `COOKIE_SECURE=true`, `listen 443 ssl` + редирект с 80.

### 2026-11-18 — сертификат GoGetSSL, HTTPS на втором IP

- В `CSR.txt` пришли CSR, приватный ключ и цепочка. Лишний блок с телом CSR под
  заголовком `CERTIFICATE` отброшен; ключ сверен с leaf-сертификатом (совпадает).
- Сертификат: CN `rompetr.autos`, SAN `rompetr.autos` + `www.rompetr.autos`,
  срок до 04.06.2027. Fullchain: leaf + GoGetSSL RSA DV SSL CA 2 + Sectigo R46;
  проверка `openssl verify` — OK.
- Установлено в `/etc/nginx/ssl/`: fullchain, leaf, ca-bundle, key (600 root).
- Обнаружен конфликт: xray Reality слушал `0.0.0.0:443`, nginx не мог занять 443.
  Xray 443-инбаунд переведён на `62.171.228.41:443`; VPN-клиенты, подключающиеся
  к `.41`, не меняются. Nginx HTTPS слушает `62.171.228.183:443`.
- Локальная проверка: `curl --resolve rompetr.autos:443:62.171.228.183` → 200
  для apex и www. HTTP-сайт пока остаётся рабочим на `.41`.
- `APP_ENV`/`APP_BASE_URL`/`COOKIE_SECURE` временно возвращены в dev/http/false,
  чтобы сайт не сломался до переключения DNS. После смены A-записей на `.183`:
  HTTPS-редирект, `APP_ENV=prod`, `https://rompetr.autos`, `COOKIE_SECURE=true`.

Осталось:

- [x] Домен `rompetr.autos` направлен на `62.171.228.41`; HTTP и DCV-файл работают.
- [x] Установить HTTPS-сертификат, переключить `APP_ENV=prod` и `COOKIE_SECURE=true`.
- [x] AI-задачи: worker использует `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`.
- [ ] Проверить полный цикл `ai_check` и `compose_news` из интерфейса CRM на VPS.
- [ ] SMTP и offsite-бэкапы.
- [ ] Проверить публикацию в тестовые VK/Telegram с VPS.

### 2026-11-19 — прод-режим и HTTPS-редирект

- Фактическое состояние на момент проверки: DNS `rompetr.autos` и `www` уже указывал
  на `62.171.228.183`; HTTP и HTTPS отдавали `200`, сертификат валиден.
- Сняты бэкапы: `/etc/rompetr-crm/app.env.bak-20261119` и
  `/etc/nginx/sites-available/rompetr.bak-20261119`.
- `/etc/rompetr-crm/app.env`: `APP_ENV=prod`, `APP_BASE_URL=https://rompetr.autos`,
  `COOKIE_SECURE=true`. Файл остаётся ASCII, без CRLF.
- nginx: HTTP-сервер теперь отдаёт `301 https://rompetr.autos$request_uri`;
  каталог `/.well-known/pki-validation/` сохранён. HTTPS-сервер не менялся.
- Выполнены `nginx -t`, `systemctl reload nginx`,
  `systemctl restart rompetr-web rompetr-worker`.
- Проверено снаружи: apex и www по HTTP → `301` на `https://rompetr.autos`;
  `/healthz` → `200 {"status":"ok"}`; `/login` → `200`; `/docs` → `404`
  (признак `APP_ENV=prod`); CSRF-cookie содержит `Secure`; HSTS отдаётся;
  `nginx`, `rompetr-web`, `rompetr-worker` — active.
- Новый конфиг nginx собран в `var/rompetr-nginx.conf` (в git не попадает).

### 2026-11-19 — гигиена репозитория и CI

- Локальная ветка синхронизирована с `origin/main` (5 коммитов со скриншотами,
  сделанных через GitHub web).
- README: скриншоты переведены на относительные пути, удалена заглушка `## ...`.
- Исправлена случайная правка в `docs/CLAUDE-CODE-DEEPSEEK-SETUP.md`: команда
  `setup-deepseek-env.ps1` была заменена на букву `в`.
- `ruff check .` — зелёный: исправлен порядок импортов в alembic, добавлены
  per-file ignores для E501 в `alembic/versions/*` и legacy `bot.py`.
- `git_guard` теперь разрешает изображения только из `docs/images/`; остальные
  PNG и медиа по-прежнему блокируются. Тест guard обновлён.
- Добавлен GitHub Actions `.github/workflows/ci.yml`: ruff, pytest и guard.
- Push сначала отклонён: у OAuth-токена `gh` не было scope `workflow`. После
  `gh auth refresh -h github.com -s workflow` ветка отправлена (`29c3906`).
- Первый запуск CI упал: консольный `pytest` не видел пакет `webapp`. В
  `pyproject.toml` добавлен `pythonpath = ["."]` (коммит `ad138cb`).
- Второй запуск упал на Linux: тест X-композера требовал локальный
  `.mcp-servers/x-mcp/x_compose.cjs`. Тест теперь подменяет наличие скрипта и
  `node` (коммит `2a2ef28`).
- CI зелёный (run `44432424002`): ruff, 47 тестов pytest и guard.
- После включения `APP_ENV=prod` проверена AI-проверка: job 10 для черновика #8,
  `succeeded` с третьей попытки (первые две — `unrecognized_model`), вердикт
  `PASS`, пост v3.

### 2026-11-19 — печать PositiveSSL

- В подвал `base.html` и на страницы входа, регистрации, сброса и восстановления
  пароля добавлена печать PositiveSSL (124×32). PNG хранится локально в
  `webapp/static/img/trust/positivessl_trust_seal_sm_124x32.png`.
- Сторонний скрипт TrustLogo не подключается: CSP `script-src 'self'` и
  `img-src 'self' data:`; печать оформлена статичной ссылкой на positivessl.com.
- Live-проверка TrustLogo для `rompetr.autos` отвечает «This website uses a
  Sectigo SSL certificate»; сам сертификат выдан GoGetSSL, цепочка ведёт к
  Sectigo Public Server Authentication Root R46.
- `git_guard` разрешает изображения только из `docs/images/` и
  `webapp/static/img/trust/`; тест guard обновлён.
- Развёрнуто на VPS 19.11.2026: `git pull` до `4f8f1ac`, `systemctl restart
  rompetr-web`; `/`, `/login` и `/register` содержат печать, статика отдаёт
  200 `image/png` (2260 байт), CSP остался прежним.

### 2026-11-19 — диагностика доступа из РФ

- `https://rompetr.autos/healthz` отдаёт 200 с внешних серверов (Microlink,
  thum.io) и с московских узлов check-host; сайт, nginx и приложение живы.
- С провайдера Nord.Com (Иркутск, AS214091) и с питерского узла check-host
  TCP 22/80/443 к `62.171.228.183` уходят в таймаут; `62.171.228.41`
  открывается на всех трёх портах. UFW открыт, fail2ban не запущен, в
  nginx-логах нет пакетов с этих адресов — трафик до VPS не доходит.
- DNS: `A 62.171.228.183`, без AAAA; `/24` анонсируется AS207728, виден
  320/320 RIS-пиров, more-specifics нет. SNI/Host `rompetr.autos` не
  блокируется: HTTP Host на `.41:80` даёт 301, TLS SNI доходит до
  Cloudflare/1.1.1.1. Причина — IP-level блок/blackhole `.183` на части
  российских маршрутов, не сервер и не домен.
- Официальный реестр РКН (`blocklist.rkn.gov.ru`) требует капчу; публичная
  выгрузка z-i от 01.10.2025 записей по `.183`/`rompetr.autos` не содержит.
  Похоже на «сожжённый» IP или TSPU-фильтр; официальную запись нужно
  проверить вручную.
- Варианты: Cloudflare proxy (с провайдера edge доступен, colo DME), новый
  IP у провайдера, российский reverse proxy/CDN. Переезд на `.41` не
  рассматривался без решения по xray Reality на `.41:443`. Решение не
  принято, конфигурация VPS не менялась.

### 2026-11-19 — страница архива черновиков

- Перенос в архив (`POST /drafts/{id}/archive`) теперь ведёт на `/archive`;
  архивные посты исключены из списка `/drafts`.
- `/archive` повторяет страницу черновиков: админ видит все архивные посты,
  остальные — только свои. В шапке рядом с «Кабинет» добавлена ссылка «Архив».
- Файлы: `webapp/routers/drafts.py`, `webapp/templates/drafts/list.html`,
  `webapp/templates/base.html`; тест
  `tests/test_drafts.py::test_archive_page_lists_only_archived_and_scopes_by_author`.
- Проверки: `ruff` и полный pytest — зелёные. На VPS после деплоя перенести
  тестовый черновик в архив и проверить `/archive` под админом и гостем.

### 2026-11-19 — переписка в тикетах

- `/tickets` теперь ведёт на `/tickets/{id}`: пользователь видит переписку
  (кроме внутренних заметок) и может ответить в открытом тикете.
- Ответ в закрытый тикет запрещён; для POST обязателен CSRF-токен.
- Файлы: `webapp/routers/tickets.py`, `webapp/templates/tickets/list.html`,
  `webapp/templates/tickets/detail.html`, `tests/test_tickets.py`.
- Проверки: `ruff` и pytest — зелёные. На VPS после деплоя открыть тикет и
  отправить ответ под гостевым пользователем.

### 2026-11-19 — статусы тикетов в админке

- На `/admin/tickets/{id}` добавлены действия «В работу», «Закрыть» и
  «Переоткрыть»; закрытый тикет получает `closed_at`, при переоткрытии поле
  очищается.
- Новый маршрут `POST /admin/tickets/{id}/status` принимает только `open`,
  `in_progress`, `closed`, пишет смену статуса в аудит.
- Файлы: `webapp/routers/admin.py`, `webapp/templates/admin/ticket_detail.html`,
  `tests/test_tickets.py`.
- Проверки: `ruff` и pytest — зелёные. На VPS после деплоя сменить статус
  тикета и проверить, что пользователь видит закрытый тикет только для чтения.

### 2026-11-19 — переезд HTTPS на `85.136.181.69`

- Провайдер удалил `62.171.228.183` с `ens18` и выдал `85.136.181.69`;
  DNS A переключён на `.69` (TTL 300), `www` — CNAME на домен, AAAA нет.
- nginx: `listen 62.171.228.183:443` заменён на `listen 85.136.181.69:443`;
  `nginx -t` успешно, выполнен `systemctl reload nginx`.
- `gost-claude`: `interface=62.171.228.183` заменён на
  `interface=85.136.181.69`; `daemon-reload` и restart; исходящий IP через
  прокси — `.69`.
- Резервные копии: `/etc/nginx/sites-available/rompetr.bak-20261119-090157`,
  `/etc/systemd/system/gost-claude.service.bak-20261119-090157`.
- Причина, почему 443 не отвечал: nginx был привязан к уже удалённому `.183`;
  порт 80 слушал `0.0.0.0`, поэтому 80 и 22 работали, а 443 таймаутил из всех
  стран, не только из РФ.
- Проверки: TCP 443 открыт с ru1/ru2/ru3 (Москва, Санкт-Петербург), de1, nl1,
  us1, kz1, tr1. `https://rompetr.autos/healthz` отдаёт 200 из Германии,
  Нидерландов, Казахстана, Турции, Канады, Франции, Японии, Швеции, Сингапура,
  Великобритании и US2/US3. Отдельный прогон Globalping: 50/50 российских проб
  в 24 городах (Москва, Санкт-Петербург, Казань, Екатеринбург, Новосибирск,
  Владивосток, Хабаровск, Краснодар, Сочи и др.) — 200. Узел check-host us1
  дал таймаут только на HTTP, при этом его TCP 443 был открыт, а пять US-проб
  Globalping дошли до nginx.
- Сертификат GoGetSSL для `rompetr.autos`/`www` валиден до 04.06.2027.
- DNS: авторитативные `ns1/ns2.e-ns.org` отдают `.69`; Google и Cloudflare DoH
  тоже `.69`, TTL 300. Старые кеши с прежним TTL 21600 могут держать `.183`
  до ~6 часов.
- Ловушка: локальный Windows-резолвер через `throne-tun` показывал старый
  `.183`; авторитативные записи проверять с VPS или через DoH.

### 2026-11-19 — `compose_news`: приём площадок строками

- Job 12 (черновик 10) упал: DeepSeek записал `platforms` строками
  (`"telegram": "…"`), а схема `PostDocument` ждала `{"content": "…"}`;
  JSON не применился, черновик остался пустым, квота не списалась.
- `PlatformText` теперь принимает и строку, и объект (валидатор
  `accept_plain_text`), промпт `_compose_prompt` задаёт форму с примером;
  регрессия — `tests/test_post_document.py`.
- Деплой: коммит `62bb041`, `rompetr-worker` и `rompetr-web` перезапущены,
  `/healthz` — 200.
- Ловушка: упавшую задачу `compose_news` автоматически никто не повторяет —
  нужно снова нажать «Запустить» в черновике; лимит при этом не тратится.

### 2026-11-20 — «Одобрить» → «Сделать пользователем»

- Причина: в `/admin/users` кнопка «Одобрить» читалась как активация гостя,
  хотя `approve_user` меняет `role=guest` на `user` и отключает гостевые лимиты.
  Из-за этого `testuser` дважды терял гостевой режим (audit `admin.user_approved`
  в 16:24:57 и 16:42:33).
- Кнопка переименована в «Сделать пользователем»; над таблицей добавлено
  пояснение, что действие меняет роль и отключает гостевые лимиты.
- Файлы: `webapp/templates/admin/users.html`, `tests/test_auth_flow.py`.
- Проверки: `ruff` и 61 pytest — зелёные, `git_guard` — 0.
- Деплой: коммит `0134c99`, `rompetr-web` перезапущен, `/healthz` — 200,
  `testuser` остаётся `role=guest`, `status=active`.

### 2026-11-21 — VK ID: фото на стене сообщества

- Причина: ключ сообщества VK не умеет `photos.*` (`error 27`), поэтому PNG
  прикрепляется пользовательским токеном VK ID с правом `photos`, а
  `wall.post` выполняется текущим ключом сообщества.
- Добавлены `VK_CLIENT_ID`, `VK_SERVICE_KEY`, `VK_SECRET_KEY`,
  `VK_REDIRECT_URI`, `VK_OAUTH_SCOPE`, `VK_OAUTH_FILE`.
- OAuth 2.1 + PKCE: `/admin/vk/connect` → VK ID → `/admin/vk/callback`;
  `state` и `code_verifier` лежат в подписанной HttpOnly-cookie, токены — в
  `var/secrets/vk_oauth.json` (каталог `700`, файл `600`, владелец `cpapp`).
- `webapp/services/vk.py`: refresh с ротацией refresh token, загрузка
  `getWallUploadServer` → multipart → `saveWallPhoto`, fallback на текст с
  примечанием, если фото прикрепить не удалось.
- Файлы: `webapp/services/vk.py`, `webapp/routers/admin.py`,
  `webapp/templates/admin/vk.html`, `webapp/config.py`,
  `webapp/services/publish.py`, `.env.example`, `README.md`, `tests/test_vk.py`.
- Проверки: `ruff` и 70 pytest — зелёные.
- Деплой: коммит `130b2d4`; в `/etc/rompetr-crm/app.env` добавлены
  `VK_CLIENT_ID`, `VK_SERVICE_KEY`, `VK_SECRET_KEY`, `VK_REDIRECT_URI`,
  `VK_OAUTH_SCOPE`, `VK_OAUTH_FILE` (значения не печатались), создан
  `/srv/rompetr/crm/var/secrets` (`cpapp:cpmedia`, `700`), сервисы
  перезапущены, `/healthz` — 200.
- Ловушка: VK ID user token (`vk2.a.*`) по отчётам 2026 года может не
  приниматься VK API (`error 1051`). После авторизации сразу проверить
  `photos.getWallUploadServer`; при 1051 нужен legacy-токен `vk1.a.*` или
  вариант B/C из `docs/VK-PHOTO-PUBLISHING.md`.

### 2026-11-21 — VK ID подключён: не хватает доступа photos

- Владелец подключил приложение через `/admin/vk`: `token_status` —
  `connected: true`, `user_id: 852659808`, `scope: vkid.personal_info`,
  токен формата `vk2.a.*`; refresh доступен.
- Диагностика с VPS: `users.get` — OK (Роман Петров); `photos.getWallUploadServer`
  — `error 15: Access denied: no access to call this method. It cannot be
  called with current scopes`; `account.getAppPermissions` и
  `apps.getScopes` — `error 1051` (ограничение профиля `vk2.a.*`).
- Вывод: токен `vk2.a.*` метод `photos.getWallUploadServer` принимает, но у
  приложения нет расширенного доступа `photos`. Это не случай Postiz #1408
  (там 1051 на `wall.post`). Нужно включить «Фотографии» в кабинете VK ID
  (Доступы → Расширенные доступы) либо отправить письмо на
  `devsupport@corp.vk.com`; черновик письма с `app_id 54912176` и текстом
  ошибки — в `docs/VK-PHOTO-PUBLISHING.md`, раздел 6.
- После включения: «Переподключить VK ID» на `/admin/vk`, затем повторить
  `photos.getWallUploadServer`. Публикация поста #15 (draft, PNG 1024×1024)
  ещё не выполнялась.
- 21.11.2026 владелец отправил письмо в `devsupport@corp.vk.com` с запросом
  `photos`; ждём ответа. Задача приостановлена до ответа поддержки.

---

## 3. Открытые вопросы

| ID  | Вопрос                                  | Текущее допущение                                          |
| --- | --------------------------------------- | ---------------------------------------------------------- |
| Q1  | SMTP-провайдер и ADMIN_EMAIL            | dev-режим, письма в `var/mail/`                            |
| Q2  | DNS и способ сертификата                | Закрыт: DNS на `.69`, сертификат GoGetSSL до 04.06.2027    |
| Q3  | VPS: IP, ресурсы, SSH                   | 2 vCPU / 4 ГБ / 40 ГБ                                      |
| Q4  | Правит ли гость черновик после отправки | Нет                                                        |
| Q5  | Кто публикует                           | user — свой approved; guest — 1 публикация после одобрения |
| Q6  | Модель Claude для worker                | `deepseek-flash` через Anthropic-совместимый endpoint      |
| Q7  | Импорт старых JSON                      | Оставить на диске                                          |
| Q8  | Offsite-бэкапы                          | Backblaze B2 через restic                                  |

---

## 4. Что ещё не сделано

- Роль `moderator` — только в планах.
- Планировщик `scheduled_at` есть в CLI, но нет поля в UI черновика.
- SMTP для реальных писем; сейчас dev-режим.
- Offsite-бэкапы и мониторинг.
- Проверить полный цикл `compose_news` после включения `APP_ENV=prod`
  (`ai_check` уже проверен 19.11.2026).
- Автоматическая публикация X через API не используется — только ручная очередь.
