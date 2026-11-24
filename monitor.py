#!/usr/bin/env python3
"""
Realitný monitor – sleduje nové inzeráty na realitných portáloch
a posiela ich na Telegram.

Použitie:
  python3 monitor.py            beží nonstop (kontrola každých X minút)
  python3 monitor.py --raz      jedna kontrola a koniec (napr. pre cron)
  python3 monitor.py --test     ukáže, čo nájde, nič neuloží + pošle testovaciu správu
  python3 monitor.py --chat-id  vypíše tvoje Telegram chat_id
"""
import argparse
import html
import os
import random
import re
import smtplib
import sqlite3
import sys
import time
import tomllib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import okresy

LOK = None  # Lokator okresov – nastaví sa v main()

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.toml"
DB_PATH = BASE / "videne.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "sk-SK,sk;q=0.9,cs;q=0.8,en;q=0.5",
}

# Ako vyzerá odkaz na detail inzerátu na jednotlivých portáloch.
# Pre portály, ktoré tu nie sú, sa použije všeobecné pravidlo nižšie.
DETAIL_PATTERNS = {
    "bazos.sk": [r"/inzerat/\d+/"],
    "nehnutelnosti.sk": [r"/detail/[^/?#]+", r"^/\d{6,}/"],
    "topreality.sk": [r"-r\d{5,}\.html$"],
}
GENERIC_PATTERNS = [r"/detail/", r"/inzerat/", r"\d{6,}"]
SKIP_LINK = re.compile(
    r"(login|prihlas|registr|kontakt|cookie|gdpr|pridat|pridaj|oblubene|favorit|"
    r"javascript:|mailto:|tel:|facebook\.com|instagram\.com|google\.)",
    re.I,
)

# Heuristika súkromník / realitka (hľadá sa v texte detailu inzerátu)
PRIVATE_WORDS = [
    "súkromná osoba", "sukromna osoba", "súkromný predaj", "sukromny predaj",
    "nie rk", "rk nevolať", "rk nevolat", "rk prosím nevolať", "realitky nevolať",
    "realitky nevolat", "bez rk", "bez realitky", "bez realitnej", "priamo od majiteľa",
    "priamo od majitela", "od majiteľa", "od majitela", "nie som realitka",
    "nie som rk", "realitným kanceláriám ďakujem", "realitné kancelárie nevolať",
]
AGENCY_WORDS = [
    "realitná kancelária", "realitna kancelaria", "realitnej kancelárie",
    "realitný maklér", "realitny makler", "maklér", "makler", "provízia",
    "provizia", "provízie", "rezervačná zmluva", "exkluzívne ponúkame",
    "exkluzivne ponukame", "ponúkame na predaj", "ponukame na predaj",
    "v zastúpení", "zastupujeme",
]
NEXT_TEXT = re.compile(r"^(ďalšia|dalsia|ďalej|dalej|ďalšie|ďalších|další|next|›|»|>|→)", re.I)
PRICE_RE = re.compile(r"(\d{1,3}(?:[   .]\d{3})+|\d{3,7})\s*(?:€|eur\b)", re.I)


# ---------------------------------------------------------------- pomocné

def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(f"Chýba súbor {CONFIG_PATH.name} – musí byť v rovnakom priečinku ako monitor.py")
    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    cfg.setdefault("nastavenia", {})
    cfg.setdefault("hladanie", [])
    return cfg


def base_domain(netloc):
    parts = netloc.lower().split(":")[0].split(".")
    return ".".join(parts[-2:])


def fetch(url, session):
    r = session.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    return r.text


def polite_pause():
    time.sleep(random.uniform(2.0, 5.0))


# ---------------------------------------------------------------- databáza

def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS videne ("
        " kluc TEXT PRIMARY KEY, hladanie TEXT, nazov TEXT, url TEXT, prvykrat TEXT)"
    )
    con.execute("CREATE TABLE IF NOT EXISTS hladania (nazov TEXT PRIMARY KEY, od TEXT)")
    return con


def is_initialized(con, name):
    return con.execute("SELECT 1 FROM hladania WHERE nazov=?", (name,)).fetchone() is not None


def mark_initialized(con, name):
    con.execute("INSERT OR IGNORE INTO hladania VALUES (?, ?)", (name, datetime.now().isoformat()))
    con.commit()


def is_seen(con, key):
    return con.execute("SELECT 1 FROM videne WHERE kluc=?", (key,)).fetchone() is not None


def mark_seen(con, key, search, title, url):
    con.execute(
        "INSERT OR IGNORE INTO videne VALUES (?, ?, ?, ?, ?)",
        (key, search, title, url, datetime.now().isoformat()),
    )


# ---------------------------------------------------------------- parsovanie

def listing_key(url):
    p = urlparse(url)
    return (p.netloc.lower().removeprefix("www.") + p.path.rstrip("/")).lower()


def is_detail_link(abs_url, search_domain):
    p = urlparse(abs_url)
    if p.scheme not in ("http", "https"):
        return False
    if base_domain(p.netloc) != search_domain:
        return False
    if SKIP_LINK.search(abs_url):
        return False
    patterns = None
    for dom, pats in DETAIL_PATTERNS.items():
        if base_domain(p.netloc) == dom:
            patterns = pats
            break
    patterns = patterns or GENERIC_PATTERNS
    return any(re.search(pat, p.path) for pat in patterns)


def extract_listings(page_html, page_url):
    """Vráti {kluc: {"url", "nazov"}} všetkých inzerátov na stránke výsledkov."""
    soup = BeautifulSoup(page_html, "html.parser")
    domain = base_domain(urlparse(page_url).netloc)
    found = {}
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(page_url, a["href"]).split("#")[0]
        if not is_detail_link(abs_url, domain):
            continue
        key = listing_key(abs_url)
        text = " ".join(a.get_text(" ", strip=True).split()) or a.get("title", "")
        item = found.setdefault(key, {"url": abs_url.split("?")[0] if "bazos" in domain else abs_url, "nazov": ""})
        if len(text) > len(item["nazov"]):
            item["nazov"] = text[:200]
    return found


def find_next_page(page_html, page_url):
    """Nájde odkaz na ďalšiu stranu výsledkov (rel=next alebo text „Ďalšia“, „»“...)."""
    soup = BeautifulSoup(page_html, "html.parser")
    link = soup.find("a", rel="next") or soup.find("link", rel="next")
    if not link:
        for a in soup.find_all("a", href=True):
            t = a.get_text(" ", strip=True) or a.get("aria-label", "") or a.get("title", "")
            if t and len(t) < 25 and NEXT_TEXT.match(t):
                link = a
                break
    if link and link.get("href"):
        nxt = urljoin(page_url, link["href"]).split("#")[0]
        if nxt != page_url:
            return nxt
    return None


def parse_price(text):
    m = PRICE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def analyze_detail(page_html):
    """Z detailu inzerátu vytiahne názov, cenu a odhad, či ide o súkromníka."""
    soup = BeautifulSoup(page_html, "html.parser")
    og = soup.find("meta", property="og:title")
    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else "") or (og["content"] if og and og.get("content") else "")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = " ".join(main.get_text(" ", strip=True).split())
    low = text.lower()

    if any(w in low for w in PRIVATE_WORDS):
        seller = "sukromnik"
    elif any(w in low for w in AGENCY_WORDS):
        seller = "rk"
    else:
        seller = "nezname"
    return {"nazov": title, "cena": parse_price(text), "predajca": seller, "text": low, "text_raw": text}


# ---------------------------------------------------------------- filtre

def passes_filters(item, st):
    text = (item.get("nazov", "") + " " + item.get("text", "")).lower()
    must = [w.lower() for w in st.get("musi_obsahovat", [])]
    must_not = [w.lower() for w in st.get("nesmie_obsahovat", [])]
    if must and not any(w in text for w in must):
        return False
    if any(w in text for w in must_not):
        return False
    price = item.get("cena")
    if price:
        if st.get("cena_od") and price < st["cena_od"]:
            return False
        if st.get("cena_do") and price > st["cena_do"]:
            return False
    if st.get("iba_sukromnici") and item.get("predajca") == "rk":
        return False
    povolene = st.get("okresy", [])
    if povolene:
        if item.get("okres"):
            if not okresy.okres_vyhovuje(item["okres"], povolene):
                return False
        elif not st.get("posielat_neznamy_okres", True):
            return False
    return True


# ---------------------------------------------------------------- Telegram

def tg_credentials(cfg):
    """Token a chat_id: najprv z premenných prostredia (GitHub Secrets), potom z config.toml."""
    tg = cfg.get("telegram", {})
    token = os.environ.get("TELEGRAM_TOKEN") or tg.get("token", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or str(tg.get("chat_id", ""))
    return token.strip(), chat_id.strip()


def tg_send(cfg, text):
    token, chat_id = tg_credentials(cfg)
    if not token or "SEM_" in token or not chat_id:
        if not email_enabled(cfg):
            log("  (Telegram ani e-mail nie sú nastavené – správa len tu):\n" + text)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
        if not r.ok:
            log(f"  Telegram chyba {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        log(f"  Telegram nedostupný: {e}")
    time.sleep(1.2)


BADGE_SHORT = {"sukromnik": "🟢", "rk": "🏢", "nezname": "❔"}


def send_digest(cfg, search_name, items):
    """Veľa nových naraz → jeden súhrn (rozdelený podľa limitu Telegramu)."""
    header = f"🏠 <b>{len(items)} nových inzerátov</b> – {html.escape(search_name)}\n"
    # súkromníci navrch
    order = {"sukromnik": 0, "nezname": 1, "rk": 2}
    items = sorted(items, key=lambda i: (i.get("okres") or "~", order.get(i.get("predajca"), 1)))
    chunk, current = header, None
    for it in items:
        okres = it.get("okres") or "okres neurčený"
        if okres != current:
            current = okres
            kraj = LOK.kraj(okres) if LOK else ""
            head = f"\n📍 <b>{html.escape(okres)}</b>" + (f" · {kraj}" if kraj else "") + "\n"
            if len(chunk) + len(head) > 3800:
                tg_send(cfg, chunk)
                chunk = header.replace("nových", "nových (pokr.)")
            chunk += head
        price = f" – {it['cena']:,} €".replace(",", " ") if it.get("cena") else ""
        line = (f"\n{BADGE_SHORT.get(it.get('predajca'), '•')} "
                f"{html.escape((it.get('nazov') or '(bez názvu)')[:90])}{price}\n{it['url']}\n")
        if len(chunk) + len(line) > 3800:
            tg_send(cfg, chunk)
            chunk = header.replace("nových", "nových (pokr.)")
        chunk += line
    tg_send(cfg, chunk)


# ---------------------------------------------------------------- E-mail

EMAIL_BUFFER = []   # (hladanie, item) – všetko nové z jednej kontroly → jeden e-mail
EMAIL_WARN = []     # varovania do e-mailu


def email_credentials(cfg):
    em = cfg.get("email", {})
    user = (os.environ.get("EMAIL_USER") or em.get("od", "")).strip()
    pwd = (os.environ.get("EMAIL_APP_PASSWORD") or em.get("heslo_aplikacie", "")).replace(" ", "").strip()
    to = (os.environ.get("EMAIL_TO") or em.get("komu", "") or user).strip()
    return user, pwd, to


def email_enabled(cfg):
    user, pwd, _ = email_credentials(cfg)
    return bool(user and pwd)


def email_send(cfg, subject, body_html, body_text=""):
    user, pwd, to = email_credentials(cfg)
    if not (user and pwd):
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Realitný monitor <{user}>", to
    msg.attach(MIMEText(body_text or subject, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(user, pwd)
            smtp.sendmail(user, [a.strip() for a in to.split(",") if a.strip()], msg.as_string())
        log(f"  E-mail odoslaný: {subject}")
    except Exception as e:  # noqa
        log(f"  E-mail sa nepodarilo odoslať: {e}")


def flush_email(cfg):
    """Pošle jeden e-mail so všetkými novými inzerátmi z tejto kontroly."""
    global EMAIL_BUFFER, EMAIL_WARN
    if not email_enabled(cfg) or not (EMAIL_BUFFER or EMAIL_WARN):
        EMAIL_BUFFER, EMAIL_WARN = [], []
        return
    items = EMAIL_BUFFER
    n_priv = sum(1 for _, it in items if it.get("predajca") == "sukromnik")
    if len(items) == 1:
        _, it = items[0]
        subject = f"🏠 {it.get('nazov') or 'Nový inzerát'}"[:120]
        if it.get("okres"):
            subject += f" – {it['okres']}"
    elif items:
        subject = f"🏠 {len(items)} nových inzerátov" + (f" ({n_priv}× súkromník)" if n_priv else "")
    else:
        subject = "⚠️ Realitný monitor – upozornenie"

    order = {"sukromnik": 0, "nezname": 1, "rk": 2}
    items = sorted(items, key=lambda x: (x[1].get("okres") or "~", order.get(x[1].get("predajca"), 1)))
    badge = {"sukromnik": "🟢 súkromník", "rk": "🏢 realitka", "nezname": "❔ predajca neznámy"}
    parts = ['<div style="font-family:Arial,sans-serif;font-size:15px;max-width:640px">']
    for w in EMAIL_WARN:
        parts.append(f'<p style="background:#fff3cd;padding:8px">{w}</p>')
    current, lines_txt = None, []
    for search_name, it in items:
        okres = it.get("okres") or "okres neurčený"
        if okres != current:
            current = okres
            kraj = LOK.kraj(okres) if LOK else ""
            parts.append(f'<h3 style="margin:18px 0 6px">📍 {html.escape(okres)}'
                         + (f' <span style="color:#777;font-weight:normal">· {kraj}</span>' if kraj else "") + "</h3>")
            lines_txt.append(f"\n== {okres} ==")
        price = f"{it['cena']:,} €".replace(",", " ") if it.get("cena") else "cena neuvedená"
        title = html.escape(it.get("nazov") or "(bez názvu)")
        parts.append(
            f'<p style="margin:0 0 12px"><a href="{html.escape(it["url"])}" style="font-weight:bold">{title}</a><br>'
            f'💶 {price} &nbsp; {badge.get(it.get("predajca"), "")}<br>'
            f'<span style="color:#777;font-size:13px">{html.escape(search_name)}</span></p>')
        lines_txt.append(f"{it.get('nazov','')} | {price} | {it['url']}")
    parts.append("</div>")
    email_send(cfg, subject, "".join(parts), "\n".join(lines_txt))
    EMAIL_BUFFER, EMAIL_WARN = [], []


def format_message(search_name, item):
    badge = {"sukromnik": "🟢 SÚKROMNÍK", "rk": "🏢 realitka", "nezname": "❔ predajca neznámy"}
    lines = [f"🏠 <b>Nový inzerát</b> – {html.escape(search_name)}"]
    lines.append(html.escape(item.get("nazov") or "(bez názvu)"))
    if item.get("cena"):
        lines.append(f"💶 {item['cena']:,} €".replace(",", " "))
    if item.get("predajca"):
        lines.append(badge.get(item["predajca"], ""))
    if item.get("okres"):
        kraj = LOK.kraj(item["okres"]) if LOK else ""
        lines.append(f"📍 okres {html.escape(item['okres'])}" + (f" · {kraj}" if kraj else ""))
    else:
        lines.append("📍 okres neurčený")
    lines.append(item["url"])
    return "\n".join(lines)


def print_chat_id(cfg):
    token, _ = tg_credentials(cfg)
    if not token or "SEM_" in token:
        sys.exit("Najprv vlož token od @BotFather do config.toml.")
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    chats = {}
    for u in r.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        c = msg.get("chat")
        if c:
            chats[c["id"]] = c.get("first_name") or c.get("title") or ""
    if not chats:
        print("Nič som nenašiel. Napíš svojmu botovi v Telegrame „ahoj“ a spusti to znova.")
    for cid, name in chats.items():
        print(f"chat_id = {cid}   ({name})")


# ---------------------------------------------------------------- hlavná logika

zero_counter = {}


def check_search(search, cfg, con, session, test=False):
    name, url = search.get("nazov", "?"), search.get("url", "")
    if not url.startswith("http") or search.get("vypnute"):
        return 0
    st = cfg["nastavenia"]
    max_pages = int(search.get("strany", st.get("strany", 3)))
    initialized = is_initialized(con, name)
    log(f"Kontrolujem: {name}")

    listings, page_url, page_no = {}, url, 0
    while page_url and page_no < max_pages:
        page_no += 1
        try:
            page_html = fetch(page_url, session)
        except requests.RequestException as e:
            log(f"  Chyba pri načítaní strany {page_no}: {e}")
            break
        page_items = extract_listings(page_html, page_url)
        listings.update(page_items)
        # zoradené od najnovších → keď je celá strana už videná, ďalej nemusíme
        if initialized and page_items and all(is_seen(con, k) for k in page_items):
            break
        page_url = find_next_page(page_html, page_url)
        if page_url and page_no < max_pages:
            polite_pause()

    log(f"  Na {page_no} stranách {len(listings)} inzerátov")
    if not listings:
        zero_counter[name] = zero_counter.get(name, 0) + 1
        if zero_counter[name] == 3 and not test:
            EMAIL_WARN.append(f"⚠️ „{html.escape(name)}“ 3× za sebou nenašiel žiadne inzeráty – skontroluj URL.")
            tg_send(cfg, f"⚠️ Monitor: „{html.escape(name)}“ 3× za sebou nenašiel žiadne inzeráty. "
                         "Skontroluj URL alebo sa zmenil web.")
        return 0
    zero_counter[name] = 0

    if test:
        for i, item in enumerate(list(listings.values())[:5]):
            extra = ""
            if i < 2:  # pri dvoch skúsi otvoriť detail a určiť okres, cenu, predajcu
                polite_pause()
                try:
                    d = analyze_detail(fetch(item["url"], session))
                    okres = LOK.najdi(d["nazov"] or item["nazov"], d["text_raw"]) if LOK else ""
                    extra = f"   [okres: {okres or '?'}, cena: {d['cena'] or '?'}, predajca: {d['predajca']}]"
                except requests.RequestException as e:
                    extra = f"   [detail chyba: {e}]"
            print(f"    • {item['nazov'][:70]}  →  {item['url']}{extra}")
        return 0

    if not initialized:
        for key, item in listings.items():
            mark_seen(con, key, name, item["nazov"], item["url"])
        mark_initialized(con, name)
        con.commit()
        log("  Prvé spustenie – súčasné inzeráty si zapamätám, upozorním až na nové.")
        return 0

    new = [(k, it) for k, it in listings.items() if not is_seen(con, k)]
    to_send = []
    for key, item in new:
        if st.get("otvarat_detail", True):
            polite_pause()
            try:
                detail = analyze_detail(fetch(item["url"], session))
                item.update({k: v for k, v in detail.items() if v and not (k == "nazov" and len(v) < len(item["nazov"]) // 2)})
            except requests.RequestException as e:
                log(f"  Detail sa nenačítal ({e}), posielam bez neho")
        item["okres"] = LOK.najdi(item.get("nazov", ""), item.get("text_raw", "")) if LOK else ""
        mark_seen(con, key, name, item["nazov"], item["url"])
        con.commit()
        if passes_filters(item, st):
            to_send.append(item)

    EMAIL_BUFFER.extend((name, it) for it in to_send)
    limit = int(st.get("max_samostatnych_sprav", 5))
    if len(to_send) > limit:
        send_digest(cfg, name, to_send)
    else:
        for item in to_send:
            tg_send(cfg, format_message(name, item))
    log(f"  Nových: {len(new)}, odoslaných po filtroch: {len(to_send)}")
    return len(to_send)


def run_once(cfg, con, session, test=False):
    searches = cfg["hladanie"]
    if not searches:
        log("V config.toml nie je žiadne [[hladanie]].")
    for s in searches:
        check_search(s, cfg, con, session, test=test)
        polite_pause()
    if not test:
        flush_email(cfg)


def main():
    ap = argparse.ArgumentParser(description="Realitný monitor")
    ap.add_argument("--raz", action="store_true", help="jedna kontrola a koniec")
    ap.add_argument("--test", action="store_true", help="skúšobné spustenie bez ukladania")
    ap.add_argument("--chat-id", action="store_true", help="zistiť Telegram chat_id")
    args = ap.parse_args()

    cfg = load_config()
    if args.chat_id:
        print_chat_id(cfg)
        return

    global LOK
    LOK = okresy.Lokator(log=log)
    con = db_connect()
    session = requests.Session()

    if args.test:
        tg_send(cfg, "✅ Realitný monitor: testovacia správa – Telegram funguje.")
        if email_enabled(cfg):
            email_send(cfg, "✅ Realitný monitor – testovací e-mail",
                       "<p>E-mailové upozornenia fungujú. Nové inzeráty ti budú chodiť sem.</p>")
        else:
            log("E-mail nie je nastavený (EMAIL_USER / EMAIL_APP_PASSWORD) – posielam len Telegram.")
        run_once(cfg, con, session, test=True)
        return
    if args.raz:
        run_once(cfg, con, session)
        return

    interval = max(3, int(cfg["nastavenia"].get("interval_minut", 10)))
    log(f"Monitor beží, kontrola každých ~{interval} min. Zastavíš Ctrl+C.")
    while True:
        try:
            run_once(cfg, con, session)
        except Exception as e:  # monitor nesmie spadnúť kvôli jednej chybe
            log(f"Neočakávaná chyba: {e!r}")
        time.sleep(interval * 60 + random.uniform(-30, 60))


if __name__ == "__main__":
    main()
