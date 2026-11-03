# Міграція на агентне ревʼю (гілка `feature/agent`)

## Рішення (зафіксовано)

- Нічого не блокуємо: ні PR, ні локальні хуки. Ревʼю — лише порада.
- LLM: корпоративний Qwen на SGLang, 128k контекст, доступний з інтернету (GitHub-hosted runner підходить).
- Thinking-режим вимкнено на старті (`llm.extra_body`), A/B у фазі 7.
- OpenAI-compatible API, без нових фреймворків. Цикл агента ~100 рядків.
- `engine: classic` лишається як fallback і база для порівняння.
- Деградація: agent → classic (та сама модель) → static. Завжди exit 0.

## Фаза 0 — Прескоуп
- [x] Перевірити tool calling на SGLang і поведінку thinking (працює; thinking увімкнений за замовчуванням, reasoning у `reasoning_content`)
- [x] Фаза 3b (текстовий протокол) не потрібна
- [x] Додати `review.py --test-tools`, `llm.extra_body` (thinking вимкнено в `review_config.json`)
- [x] Прибрати `fallback_model` (claude-haiku) з `review_config.json`
- [x] `llm.model = qwen3.8-27b`, `llm.base_url` прибрано з репо (лише `LLM_BASE_URL`)
- [ ] У фазі 7 оновити README, `.github/copilot-instructions.md`, `review_config_rust_example.json` (досі anthropic/opencode)

## Фаза 1 — `RepoSource`
- [x] Клас у `diff_parser.py`: `read` / `list_dir` / `find_files` / `grep` для режимів index, worktree, git rev (`RepoSource.for_diff_mode`)
- [x] Захист шляхів (`../`, symlinks), deny-list (`.env*`, `*.pem`, `id_rsa*`)
- [x] Тести на temp-репо (`test_repo_source.py`): index / worktree / rev, захист шляхів, deny-list

## Фаза 2 — Інструменти (`agent_tools.py`)
- [x] `list_changed_files`, `get_diff`, `read_file`, `grep`, `find_files`, `find_definition`, `git_log`, `git_blame`
- [x] Обрізання виводу (`max_tool_output_chars`), без shell, `git grep -e <pattern>`
- [x] Тести кожного інструмента (`test_agent_tools.py`) (порожній результат, великий файл)

## Фаза 3 — Цикл агента (`agent_core.py`)
- [x] Цикл, бюджети (`max_steps`, `max_total_tokens`, `wall_timeout_sec`), примусовий `submit_review`
- [x] Qwen: вирізати `<think>`, читати `reasoning_content`, терпимий JSON аргументів, до 4 tool calls в одному повідомленні виконуються по черзі (`submit_review` завершує цикл)
- [x] `submit_review` → `ReviewResult` / `CodeSuggestion`
- [x] Пост-валідація знахідок: файл і рядок є в diff, дедуплікація, чисті `suggested_code`
- [x] Тести з фейковим клієнтом (успіх, перевищення кроків, битий JSON, невідомий інструмент, модель без tool-calls)
- [ ] (3b, лише якщо фаза 0 покаже відсутність tool calling) текстовий протокол

## Фаза 4 — CLI
- [x] `--engine agent|classic` (env `LLM_ENGINE`, конфіг `agent.enabled`), стартово classic
- [x] `--fail-on none|critical|warnings`, дефолт `none`; `--strict` як аліас `warnings`
- [x] Хуки `pre-commit` / `pre-push` завжди `exit 0`
- [x] (зроблено у фазі 3, `agent_core.py`) `--trace` друкує кроки агента; `--trace-llm` — повні запити/відповіді (CLI-прапори `--trace` / `--trace-llm` підключені до агента у фазі 4)
- [x] Оновити таблицю exit-кодів у `CLAUDE.md` (інформаційна)

## Фаза 5 — Промпт
- [x] Усі промпти винесено в `prompts/*.md` (`prompts.py`): `agent_system` (ASD-STE100, без згадки про блокування), `agent_task`, `agent_nudge`, `agent_budget_exhausted`, `classic_review`, `classic_code_suggestions`
- [x] Опційні блоки Django / Rust / Go (`prompt.language_blocks`, `agent_prompt.py`), `custom_*` правила та `check_docstrings` для агента (спільна `collect_rules`)
- [x] Тюнінг під Qwen: правило про формат повідомлення, 2 приклади в `agent_system.md` (оцінка впливу — у фазі 7)

## Фаза 6 — GitHub Action
- [x] Inputs `engine`, `max_steps`, `wall_timeout`; прибрати `fail_on_critical`, `strict`, крок «Check for failures»
- [x] `continue-on-error`, job завжди success, помилка — рядок у PR-коментарі
- [x] Прибрати `REQUEST_CHANGES`, лише `COMMENT`; один `createReview` з масивом comments
- [x] Передавати `${{ inputs.* }}` через `env:` (shell-ін'єкція в `action.yml`)
- [x] `checkout` з `ref: head.sha`, `timeout-minutes`, fork-PR без секретів — тихий skip
- [x] README: не додавати job у required checks; оновити `examples/*.yml`
- [x] Self-test workflow: matrix agent vs classic

## Фаза 7 — Оцінка і перемикання
- [x] Золоті diff (`evaluation/`, спершу 16, тепер 17 випадків): знайдені проблеми, хибні спрацювання, кроки, токени, час, частка невалідних викликів. Результат (5 прогонів): agent 65/65, точність 97%, 2 хибних; classic 60/65, точність 73%, 28 хибних
- [~] Прогін на реальних змінах (історія цього репозиторію, 12 змін, 4 класи розміру, `evaluation.history`): agent у 11 з 12 ревʼю вичерпав 20 кроків; медіана токенів 25 тис. (small) / 366 тис. (medium) / 510 тис. (large) / 563 тис. (huge), час 12–56 с проти 3–17 с у classic; 0 переходів на classic; на 35-файловому diff (`d33aa21`) agent не знайшов нічого, а classic знайшов закладені проблеми. Висновок: agent не готовий бути за замовчуванням. Ідеї: diff у першому повідомленні, жорсткіша межа кроків, гібрид «classic пропонує, agent перевіряє». Реальні PR користувача ще потрібні
- [x] Спроба зменшити вартість агента (`inline_diff_chars`, `steps_over_target`): на тих самих 12 змінах токени 4,13 → 4,50 млн (+9%), бюджет вичерпано 11 → 11; на золотих випадках повнота 100% → 95%. A/B на `cross-file-signature` (10 прогонів): diff у повідомленні 1/10, без нього 8/10. Висновок: обидві опції вимкнені за замовчуванням (код і тести лишено). Модель витрачає стільки кроків, скільки їй дозволено, тож межа лише змінює витрати; наступний крок — гібрид «classic пропонує, agent перевіряє»
- [x] A/B thinking вимкнено / увімкнено (золоті випадки, 17 × 5): повнота 65/65 в обох, час 6,3 → 11,9 с, токени +30%; на реальних змінах один запуск 506 с, ще один не завершився за 900 с (виявило нестрогий ліміт часу, виправлено). Рішення: опція `agent.thinking` / `--thinking` / `LLM_AGENT_THINKING` / вхід Action `thinking`, вимкнена за замовчуванням
- [x] `monitor.py`: рушії, кроки, токени, тривалість, частка невалідних викликів / бюджетів / переходів на classic (`monitoring.enabled`, `LLM_MONITORING`)
- [x] Гібридний engine `hybrid` (`hybrid_core.py`, `--engine hybrid`, `hybrid.*`): золоті випадки 17 × 3 — повнота 37/39 (95%), точність 90%, 5 хибних на 51 запуск, медіана 7,6 с, 3 кроки, ~7k токенів, бюджет не вичерпано; реальні зміни (12): медіана часу 2,5 / 8,2 / 27,7 / 67,1 с (small/medium/large/huge), токени агента 10k (medium), 89k (large); на huge бюджет вичерпано 3 з 3. Слабкі місця: `ctx-wrong-unit` (класик не пропонує кандидата), `safe-lookalike`
- [x] Повне рев'ю гілки (`/code-review`, 10 знахідок) і виправлення: довіра до `llm.base_url` у Action, редакція вкладених stats, deny-список у `get_diff`, timeout git, службові попередження й ліміт кандидатів у гібриді, fallback chunk-режиму, огородження suggestion, збіг коментаря старої версії, тести hybrid. `/security-review` не запустився (немає `origin/HEAD`), безпекову частину пройдено вручну
- [x] `/simplify`: один `ENGINES`, `normalize_text`, рекурсивна редакція stats, кеш імен файлів у `RepoSource`, мертвий код прибрано
- [x] CI `.github/workflows/ci.yml` (ruff 0.17.3, pytest, node-тести; Python 3.11 і 3.13), ruff без зауважень; перші запуски падали через незакріплений ruff і відсутній PyYAML (виправлено)
- [x] A/B класичного промпту за ASD-STE100 (17 × 5): повнота 60/65 в обох; точність 46% → 66% (різницю в основному дають викиди в `safe-lookalike`), знахідки без місця 3 → 0; прийнято як `prompts/classic_review.md`
- [ ] Другий раунд рев'ю з відомістю про попереднє обговорення (`--prior-file`, коментарі PR) — відкладено; повторна перевірка вже підтверджених знахідок тією ж моделлю малокорисна
- [ ] Тестовий PR на GitHub-ранері (Action з трьома engine) — потрібна людина
- [ ] Рішення про дефолт engine (за даними hybrid кращий за agent; порівняння з classic на реальних PR ще потрібне)
- [x] Оновити `CLAUDE.md`, `CHANGELOG.md`, README, `.github/copilot-instructions.md`, `review_config_rust_example.json`
- [ ] Реліз 0.1.0 (після рішення про рушій): версія, теґ, дата у `CHANGELOG.md`
- [ ] Імпорт і адаптація промпта `cloudflare/security_audit`: знайти джерело й ліцензію, перенести в `prompts/` як окремий опційний блок для безпекового аудиту (англійською, за ASD-STE100, з плейсхолдерами), підключити через `prompt.*`, оцінити на золотих випадках, додати атрибуцію

## Review
_(заповнити після завершення)_
