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
- [ ] Клас у `diff_parser.py`: `read` / `list` / `grep` для режимів index, worktree, git rev
- [ ] Захист шляхів (`../`, symlinks), deny-list (`.env*`, `*.pem`, `id_rsa*`)
- [ ] Тести на temp-репо: staged і range дають однаковий результат

## Фаза 2 — Інструменти (`agent_tools.py`)
- [ ] `list_changed_files`, `get_diff`, `read_file`, `grep`, `find_files`, `find_definition`, `git_log`, `git_blame`
- [ ] Обрізання виводу (`max_tool_output_chars`), без shell, `git grep -e <pattern>`
- [ ] Тести кожного інструмента (порожній результат, великий файл)

## Фаза 3 — Цикл агента (`agent_core.py`)
- [ ] Цикл, бюджети (`max_steps`, `max_total_tokens`, `wall_timeout_sec`), примусовий `submit_review`
- [ ] Qwen: вирізати `<think>`, читати `reasoning_content`, терпимий JSON аргументів, без parallel tool calls
- [ ] `submit_review` → `ReviewResult` / `CodeSuggestion`
- [ ] Пост-валідація знахідок: файл і рядок є в diff, дедуплікація, чисті `suggested_code`
- [ ] Тести з фейковим клієнтом (успіх, перевищення кроків, битий JSON, невідомий інструмент, модель без tool-calls)
- [ ] (3b, лише якщо фаза 0 покаже відсутність tool calling) текстовий протокол

## Фаза 4 — CLI
- [ ] `--engine agent|classic` (env `LLM_ENGINE`, конфіг `agent.enabled`), стартово classic
- [ ] `--fail-on none|critical|warnings`, дефолт `none`; `--strict` як аліас `warnings`
- [ ] Хуки `pre-commit` / `pre-push` завжди `exit 0`
- [ ] `--trace` друкує кроки агента
- [ ] Оновити таблицю exit-кодів у `CLAUDE.md` (інформаційна)

## Фаза 5 — Промпт
- [ ] `prompts/agent_system.md` (закриває пункт з `TODO.md`): роль, правила, формат, без «block commit»
- [ ] Опційні блоки Django / Rust / Go, підтягнути `custom_*` правила
- [ ] Тюнінг під Qwen: коротко, чіткий формат, 1–2 приклади

## Фаза 6 — GitHub Action
- [ ] Inputs `engine`, `max_steps`, `wall_timeout`; прибрати `fail_on_critical`, `strict`, крок «Check for failures»
- [ ] `continue-on-error`, job завжди success, помилка — рядок у PR-коментарі
- [ ] Прибрати `REQUEST_CHANGES`, лише `COMMENT`; один `createReview` з масивом comments
- [ ] Передавати `${{ inputs.* }}` через `env:` (shell-ін'єкція в `action.yml`)
- [ ] `checkout` з `ref: head.sha`, `timeout-minutes`, fork-PR без секретів — тихий skip
- [ ] README: не додавати job у required checks; оновити `examples/*.yml`
- [ ] Self-test workflow: matrix agent vs classic

## Фаза 7 — Оцінка і перемикання
- [ ] Золоті PR/diff (6–10): знайдені баги, хибні спрацювання, кроки, токени, час, частка невалідних tool-calls
- [ ] A/B thinking вимкнено / лише на фінальному кроці
- [ ] `monitor.py`: кроки, токени, тривалість
- [ ] Рішення про дефолт engine (classic лишається, якщо agent не кращий)
- [ ] Оновити `CLAUDE.md`, `CHANGELOG.md`, README; реліз 0.1.0

## Review
_(заповнити після завершення)_
