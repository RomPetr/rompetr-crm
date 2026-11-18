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
- `.env` скопировался с CRLF, pydantic не парсил булевы значения. Исправлено `sed -i 's/$//'`.
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

Осталось:

- [ ] Переключить `rompetr.ru` с 185.154.20.52 на 62.171.228.41 и выпустить TLS.
- [x] AI-задачи: worker использует `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`.
- [ ] Проверить полный цикл `ai_check` и `compose_news` из интерфейса CRM на VPS.
- [ ] SMTP и offsite-бэкапы.
- [ ] Проверить публикацию в тестовые VK/Telegram с VPS.

---

## 3. Открытые вопросы

| ID | Вопрос | Текущее допущение |
|---|---|---|
| Q1 | SMTP-провайдер и ADMIN_EMAIL | dev-режим, письма в `var/mail/` |
| Q2 | DNS и способ сертификата | DNS-01, TTL 300 |
| Q3 | VPS: IP, ресурсы, SSH | 2 vCPU / 4 ГБ / 40 ГБ |
| Q4 | Правит ли гость черновик после отправки | Нет |
| Q5 | Кто публикует | user — свой approved, guest — никогда |
| Q6 | Модель Claude для worker | `deepseek-flash` через Anthropic-совместимый endpoint |
| Q7 | Импорт старых JSON | Оставить на диске |
| Q8 | Offsite-бэкапы | Backblaze B2 через restic |

---

## 4. Что ещё не сделано

- HTMX-фрагменты: формы работают обычными POST с перезагрузкой.
- Роль `moderator` — только в планах.
- Планировщик `scheduled_at` есть в CLI, но нет поля в UI черновика.
- Telegram-письма SMTP, публичный GitHub remote и push.
- Деплой на VPS и переключение worker’а на systemd.
