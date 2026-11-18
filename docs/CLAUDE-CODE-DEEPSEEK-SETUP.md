# Claude Code через API DeepSeek на Windows 10

**Дата:** 18.11.2026
**Когда читать:** после окончания подписки Anthropic, когда Claude Code перестанет
работать через OAuth и его нужно перевести на Anthropic-совместимый API DeepSeek.

Проверено на этом компьютере: токен `ANTHROPIC_AUTH_TOKEN1` из `.env` работает,
Claude Code запускается с `API deepseek-flash` и возвращает `OK`.

---

## 1. Что понадобится

- Windows 10 и PowerShell.
- Установленный Claude Code: `claude --version`.
- Файл `.env` проекта: `C:\Users\rp\course\content\.env`.
- Значение `ANTHROPIC_AUTH_TOKEN1` в этом файле. **Никому не показывать и не коммитить.**

Claude Code ожидает токен в переменной `ANTHROPIC_AUTH_TOKEN`, поэтому значение
`ANTHROPIC_AUTH_TOKEN1` нужно присвоить именно ей. Имена `...TOKEN1` CLI не читает.

---

## 2. Какие переменные нужны

| Переменная | Значение |
|---|---|
| `ANTHROPIC_AUTH_TOKEN` | значение `ANTHROPIC_AUTH_TOKEN1` из `.env` |
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_MODEL` | `deepseek-flash` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `deepseek-flash` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `deepseek-flash` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `deepseek-flash` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `deepseek-flash` |
| `CLAUDE_CODE_EFFORT_LEVEL` | `max` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `786432` |

Удалить или очистить:

- `ANTHROPIC_API_KEY` — он перебивает токен;
- `CLAUDE_CODE_OAUTH_TOKEN` — иначе CLI может снова уйти в OAuth подписки.

**Важно по моделям.** DeepSeek принимает имена `deepseek-flash` и `deepseek-v4-pro`.
Алиасы `deepseek-v4.1-flash:cloud`, `deepseek-flash[1m]` и другие `:cloud`/`[1m]`
API отклоняет с ошибкой 400. Если нужна модель посильнее, поставьте
`ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro`, но начните с `deepseek-flash`.

---

## 3. Быстрый путь: скрипт

В PowerShell:

```powershell
cd C:\Users\rp\course\content
powershell -ExecutionPolicy Bypass -File .\scripts\setup-deepseek-env.ps1
```

Скрипт:

- читает `.env`;
- берёт именно `ANTHROPIC_AUTH_TOKEN1`;
- прописывает переменные в профиль пользователя и в текущий процесс;
- удаляет `ANTHROPIC_API_KEY` и `CLAUDE_CODE_OAUTH_TOKEN`;
- не печатает токен, выводит только имена переменных и длину токена.

Проверка без изменений:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-deepseek-env.ps1 -DryRun
```

Если не хотите сохранять токен в реестре навсегда, запустите только для текущего окна:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-deepseek-env.ps1 -SessionOnly
```

---

## 4. Ручной путь

Откройте PowerShell и выполните:

```powershell
$envFile = 'C:\Users\rp\course\content\.env'

$line = Select-String -Path $envFile -Pattern '^\s*ANTHROPIC_AUTH_TOKEN1\s*=' |
        Select-Object -Last 1
if (-not $line) { throw 'ANTHROPIC_AUTH_TOKEN1 не найден в .env' }
$token = ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
if ($token.Length -lt 20) { throw 'Токен слишком короткий' }

$vars = @{
  'ANTHROPIC_AUTH_TOKEN'             = $token
  'ANTHROPIC_BASE_URL'               = 'https://api.deepseek.com/anthropic'
  'ANTHROPIC_MODEL'                  = 'deepseek-flash'
  'ANTHROPIC_DEFAULT_SONNET_MODEL'   = 'deepseek-flash'
  'ANTHROPIC_DEFAULT_OPUS_MODEL'     = 'deepseek-flash'
  'ANTHROPIC_DEFAULT_HAIKU_MODEL'    = 'deepseek-flash'
  'CLAUDE_CODE_SUBAGENT_MODEL'       = 'deepseek-flash'
  'CLAUDE_CODE_EFFORT_LEVEL'         = 'max'
  'CLAUDE_CODE_AUTO_COMPACT_WINDOW'  = '786432'
}

foreach ($name in $vars.Keys) {
  [Environment]::SetEnvironmentVariable($name, $vars[$name], 'User')
  Set-Item -Path "Env:$name" -Value $vars[$name]
}

Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:\CLAUDE_CODE_OAUTH_TOKEN -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', $null, 'User')
[Environment]::SetEnvironmentVariable('CLAUDE_CODE_OAUTH_TOKEN', $null, 'User')

"Готово. Длина токена: $($token.Length). Откройте новый терминал."
```

---

## 5. Выйти из подписки

Даже если токен задан, старый OAuth-вход может мешать. Выполните:

```powershell
claude auth logout
claude auth status
```

Закройте все окна Claude Code. Проверьте, что переменные подписки пусты:

```powershell
[Environment]::GetEnvironmentVariable('CLAUDE_CODE_OAUTH_TOKEN', 'User')
[Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User')
```

Обе команды должны вернуть пустое значение.

---

## 6. Проверка в новом терминале

Откройте **новое** окно PowerShell — переменные уровня пользователя не попадают
в уже запущенные процессы.

```powershell
claude --version

claude -p "Reply with exactly OK" `
  --model deepseek-flash `
  --output-format json `
  --max-turns 1 `
  --max-budget-usd 0.2
```

Ожидается:

- код выхода `0`;
- `"result": "OK"`;
- в `modelUsage` ключ `deepseek-flash`;
- ненулевая стоимость запроса.

Затем запустите интерактивно:

```powershell
claude
```

Внутри проверьте `/status` и `/model`. Алиас `opus` из
`%USERPROFILE%\.claude\settings.json` продолжит работать, потому что
`ANTHROPIC_DEFAULT_OPUS_MODEL` указывает на `deepseek-flash`.

---

## 7. Проект CRM

У приложения свои настройки в `.env`: worker читает `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_BASE_URL`, `CLAUDE_MODEL` и `CLAUDE_HTTP_PROXY`. Переменные уровня
пользователя Windows могут перекрыть значения `.env`, поэтому:

- для CLI достаточно блока из раздела 2;
- если нужно, чтобы worker локального CRM тоже ходил через `TOKEN1`, замените
  `ANTHROPIC_AUTH_TOKEN` в `.env` на значение `ANTHROPIC_AUTH_TOKEN1`;
- `CLAUDE_MODEL` в `.env` должен быть `deepseek-flash`, а не `...:cloud`/`[1m]`;
- после правки перезапустите uvicorn и worker;
- на VPS уже настроен отдельный токен, его менять не нужно.

`.env` в git не попадает. Не добавляйте токен в README, коммиты и чаты.

---

## 8. Если что-то не работает

| Симптом | Что сделать |
|---|---|
| `401`, `Invalid API key`, `authentication_error` | Проверить длину токена: `$env:ANTHROPIC_AUTH_TOKEN.Length` (не печатать сам токен). Убедиться, что значение взято из `ANTHROPIC_AUTH_TOKEN1`, без кавычек и пробелов. Открыть новый терминал. |
| `400 The supported API model names are deepseek-flash, deepseek-v4-pro` | Заменить модель на `deepseek-flash` во всех `ANTHROPIC_*MODEL*`. |
| CLI снова просит вход или пишет `Not logged in` | `claude auth logout`, удалить `CLAUDE_CODE_OAUTH_TOKEN`, закрыть все окна Claude Code, открыть новый терминал. |
| Запросы идут не в DeepSeek | Проверить `$env:ANTHROPIC_BASE_URL`; удалить `ANTHROPIC_API_KEY`; выйти из OAuth. |
| `claude` не найден | Проверить `Get-Command claude`; переустановить Claude Code или добавить путь в `PATH`. |
| Скрипт `.ps1` заблокирован | Запускать как в разделе 3, с `-ExecutionPolicy Bypass`. |
| Слишком дорого | Оставить `deepseek-flash`, снизить `--max-budget-usd`, не запускать субагентов без необходимости. |

Безопасная проверка имён переменных без вывода значений:

```powershell
Get-ChildItem Env: |
  Where-Object Name -like 'ANTHROPIC*' |
  Select-Object Name, @{n='Length';e={$_.Value.Length}}
```

---

## 9. Откат на подписку

Если понадобится вернуться к Anthropic:

```powershell
foreach ($name in 'ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL','ANTHROPIC_MODEL',
                  'ANTHROPIC_DEFAULT_SONNET_MODEL','ANTHROPIC_DEFAULT_OPUS_MODEL',
                  'ANTHROPIC_DEFAULT_HAIKU_MODEL','CLAUDE_CODE_SUBAGENT_MODEL',
                  'CLAUDE_CODE_EFFORT_LEVEL','CLAUDE_CODE_AUTO_COMPACT_WINDOW') {
  [Environment]::SetEnvironmentVariable($name, $null, 'User')
  Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
claude auth login
```

---

## 10. Безопасность

- Токен хранится в реестре пользователя Windows, если запускать скрипт без
  `-SessionOnly`. Любая программа под вашей учётной записью сможет его прочитать.
- Для разового запуска используйте `-SessionOnly`.
- При подозрении на утечку перевыпустите ключ в кабинете DeepSeek и обновите `.env`.
- Не вставляйте токен в переписку, тикеты, логи и git.
