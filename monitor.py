"""
FH Monitor — стежить за новими проєктами на Freelancehunt і шле підходящі в Telegram
разом з чернеткою відгуку від Claude. Запускається GitHub Actions кожні 10 хвилин.

Секрети (GitHub → Settings → Secrets and variables → Actions):
  FH_TOKEN           — API-ключ Freelancehunt (freelancehunt.com/my/api2)
  TG_TOKEN           — токен Telegram-бота від @BotFather
  ANTHROPIC_API_KEY  — ключ Claude API (необов'язково: без нього прийде просто список проєктів)
  TG_CHAT_ID         — необов'язково: бот сам знайде твій чат, якщо ти йому щось написав
"""
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

STATE_FILE = Path(__file__).with_name("state.json")
CONFIG_FILE = Path(__file__).with_name("config.json")

FH_TOKEN = os.environ.get("FH_TOKEN", "").strip()
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip().removeprefix("bot")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

CFG = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


# ---------------- стан (що вже бачили) ----------------
def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": [], "chat_id": None, "initialized": False}


def save_state(st):
    st["seen"] = st["seen"][-500:]
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- Freelancehunt ----------------
def fetch_projects():
    headers = {"Authorization": f"Bearer {FH_TOKEN}", "Accept-Language": "uk"}
    params = {"filter[skill_id]": ",".join(str(s) for s in CFG["skill_ids"])}
    r = requests.get("https://api.freelancehunt.com/v2/projects", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    out = []
    for item in r.json().get("data", []):
        a = item.get("attributes", {})
        budget = a.get("budget") or {}
        out.append({
            "id": str(item.get("id")),
            "name": a.get("name", ""),
            "description": re.sub(r"\s+", " ", a.get("description") or "")[:3000],
            "skills": [s.get("name", "") for s in a.get("skills") or []],
            "budget": f'{budget.get("amount")} {budget.get("currency")}' if budget.get("amount") else "не вказано",
            "budget_amount": budget.get("amount"),
            "bids": a.get("bid_count", "?"),
            "published": a.get("published_at", ""),
            "status": (a.get("status") or {}).get("name", ""),
            "url": ((item.get("links") or {}).get("self") or {}).get("web", ""),
        })
    return out


def hard_excluded(p):
    text = (p["name"] + " " + p["description"]).lower()
    return any(w in text for w in CFG["exclude_words"])


# ---------------- Claude ----------------
def ask_claude(p):
    """Повертає dict: fit(bool), why(str), draft(str), price(str), days(str)."""
    prompt = f"""Ти допомагаєш фрилансеру вирішити, чи подаватись на проєкт Freelancehunt, і пишеш чернетку відгуку.

ПРО ФРИЛАНСЕРА:
{CFG["profile"]}

ПРОЄКТ:
Назва: {p["name"]}
Навички: {", ".join(p["skills"])}
Бюджет: {p["budget"]}
Ставок: {p["bids"]}
Опис: {p["description"]}

Правила оцінки:
- fit=true лише якщо задача реально по силах цьому фрилансеру і близька до його профілю (AI-боти, Telegram-боти, n8n/Make-автоматизація, інтеграції, RAG, нескладний парсинг).
- fit=false для: навчання/уроків/курсів, спаму й масових розсилок, накруток, обходу блокувань чи правил платформ, гемблінгу, вейпів, крипти, дорослого контенту, великих веб- або мобільних застосунків без AI, задач, що вимагають досвіду, якого в профілі немає.

Якщо fit=true — напиши відгук мовою замовника (українська, якщо опис українською): 4–6 речень, НЕ довше 900 символів, конкретно по задачі (як саме зробиш, на чому), з посиланням на найдоречніший проєкт портфоліо, без шаблонних фраз «маю великий досвід». Якщо замовник просить щось указати у відгуку — врахуй. Ціна: трохи нижче бюджету, але не менше 60% від нього; якщо бюджету немає — реалістична ціна в гривнях. Термін у днях.

Відповідай ТІЛЬКИ JSON без пояснень:
{{"fit": true/false, "why": "одне речення українською", "draft": "текст відгуку або порожньо", "price": "сума з валютою або порожньо", "days": "кількість днів або порожньо"}}"""
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=90, headers={
        "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": CFG["claude_model"], "max_tokens": 3000,
              "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    # запасний розбір, якщо JSON зламаний чи обрізаний
    def field(name):
        mm = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.S)
        return mm.group(1).replace('\\"', '"').replace("\\n", "\n") if mm else ""
    fit = not re.search(r'"fit"\s*:\s*false', text)
    return {"fit": fit, "why": field("why") or "відповідь Claude розібрано частково",
            "draft": field("draft"), "price": field("price"), "days": field("days")}


# ---------------- Telegram ----------------
def tg(method, **data):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", json=data, timeout=30)
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "description": f"HTTP {r.status_code}"}


def find_chat_id(st):
    if TG_CHAT_ID:
        return TG_CHAT_ID
    if st.get("chat_id"):
        return st["chat_id"]
    me = tg("getMe")
    if not me.get("ok"):
        sys.exit(f"Telegram не приймає TG_TOKEN: {me.get('description')}. Перевір секрет TG_TOKEN.")
    print("Бот за токеном:", "@" + me["result"].get("username", "?"))
    upd = tg("getUpdates")
    if not upd.get("ok") and "webhook" in str(upd.get("description", "")).lower():
        tg("deleteWebhook")
        upd = tg("getUpdates")
    if not upd.get("ok"):
        print("getUpdates помилка:", upd.get("description"))
    print("Оновлень від Telegram:", len(upd.get("result", [])))
    for u in reversed(upd.get("result", [])):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private":
            st["chat_id"] = str(chat["id"])
            return st["chat_id"]
    return None


def send(chat_id, text):
    for i in range(0, len(text), 3900):
        tg("sendMessage", chat_id=chat_id, text=text[i:i + 3900], parse_mode="HTML",
           disable_web_page_preview=True)
        time.sleep(0.5)


def fmt(p, ai=None):
    e = html.escape
    lines = [f'🆕 <b>{e(p["name"])}</b>',
             f'💰 {e(p["budget"])}  ·  📨 {e(str(p["bids"]))} ставок',
             f'🏷 {e(", ".join(p["skills"]))}',
             f'🔗 {e(p["url"])}']
    if ai:
        lines.append(f'\n💡 {e(ai.get("why", ""))}')
        if ai.get("draft"):
            lines.append(f'\n✍️ <b>Чернетка відгуку</b> (ціна: {e(ai.get("price", ""))}, термін: {e(str(ai.get("days", "")))} дн.):')
            lines.append(f'<code>{e(ai["draft"])}</code>')
    return "\n".join(lines)


def main():
    if not FH_TOKEN or not TG_TOKEN:
        sys.exit("Немає FH_TOKEN або TG_TOKEN у секретах.")
    st = load_state()
    chat_id = find_chat_id(st)
    if not chat_id:
        save_state(st)
        sys.exit("Не знайшов чат: напиши своєму боту будь-яке повідомлення в Telegram і запусти ще раз.")

    projects = fetch_projects()
    seen = set(st["seen"])
    new = [p for p in projects if p["id"] not in seen]

    if not st.get("initialized"):
        # перший запуск: не засипаємо старими проєктами, лише запам'ятовуємо
        st["seen"].extend(p["id"] for p in projects)
        st["initialized"] = True
        save_state(st)
        send(chat_id, f"✅ FH Monitor підключено! Стежу за {len(CFG['skill_ids'])} категоріями кожні 10 хвилин. "
                      f"Нові підходящі проєкти приходитимуть сюди.")
        return

    sent = 0
    for p in reversed(new):  # від старіших до новіших
        st["seen"].append(p["id"])
        if hard_excluded(p):
            continue
        ai = None
        if ANTHROPIC_KEY:
            try:
                ai = ask_claude(p)
            except Exception as ex:
                ai = {"fit": True, "why": f"Claude недоступний ({str(ex)[:80]}), перевір сам."}
            if not ai.get("fit"):
                continue
        send(chat_id, fmt(p, ai))
        sent += 1
    save_state(st)
    print(f"projects={len(projects)} new={len(new)} sent={sent}")


if __name__ == "__main__":
    main()
