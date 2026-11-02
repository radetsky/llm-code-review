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
- [ ] Золоті PR/diff (6–10): знайдені баги, хибні спрацювання, кроки, токени, час, частка невалідних tool-calls
- [ ] A/B thinking вимкнено / лише на фінальному кроці
- [ ] `monitor.py`: кроки, токени, тривалість
- [ ] Рішення про дефолт engine (classic лишається, якщо agent не кращий)
- [ ] Оновити `CLAUDE.md`, `CHANGELOG.md`, README; реліз 0.1.0

## Review
_(заповнити після завершення)_
