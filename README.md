# FH Monitor

Стежить за новими проєктами на [Freelancehunt](https://freelancehunt.com) у вибраних категоріях і надсилає підходящі в Telegram, разом з чернеткою відгуку від Claude.

**Як працює**
- GitHub Actions запускає `monitor.py` кожні 10 хвилин (7:00–24:00 за Києвом).
- Скрипт бере нові проєкти через офіційний API Freelancehunt і відсіює стоп-слова з `config.json`.
- Claude оцінює, чи проєкт підходить під профіль, і пише чернетку відгуку з ціною та терміном.
- Уже бачені проєкти зберігаються в `state.json`, тож дублів немає.

**Налаштування**
1. Secrets (Settings → Secrets and variables → Actions): `FH_TOKEN`, `TG_TOKEN`, `ANTHROPIC_API_KEY`.
2. Напиши своєму боту будь-яке повідомлення в Telegram.
3. Actions → FH Monitor → Run workflow. Перший запуск лише запам'ятовує поточні проєкти й надсилає «✅ підключено».

Категорії, стоп-слова, профіль і модель змінюються в `config.json`.

Stack: Python, GitHub Actions, Freelancehunt API v2, Telegram Bot API, Claude API.
