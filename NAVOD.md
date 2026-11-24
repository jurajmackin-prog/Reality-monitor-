# Realitný monitor – spustenie zadarmo na GitHube

Bez servera, bez platby, bez terminálu. GitHub spustí monitor každých ~10 minút a nové inzeráty z celého západného Slovenska ti pošle na Telegram aj s okresom, cenou a značkou 🟢 súkromník / 🏢 realitka.

Celé to zaberie asi 15 minút. Ide to aj z mobilu, ale z počítača je to pohodlnejšie.

---

## Krok 1 – Telegram bot (3 min)

1. V Telegrame otvor **@BotFather** → napíš `/newbot`.
2. Zadaj meno (napr. *Reality Monitor*) a používateľské meno končiace na `bot` (napr. `juraj_reality_bot`).
3. Dostaneš **token**, napríklad `7123456789:AAH...xyz`. Skopíruj si ho (nikomu ho neposielaj, ani mne).
4. Klikni na odkaz na svojho bota a napíš mu **„ahoj“**. Bez toho ti nebude môcť písať.
5. Otvor **@userinfobot** a napíš mu čokoľvek. Odpovie ti tvoje **Id** (číslo). To je tvoje `chat_id`.

## Krok 2 – GitHub účet a repozitár (3 min)

1. Zaregistruj sa na **github.com** (zadarmo).
2. Vpravo hore **+** → **New repository**.
3. Názov: `realitny-monitor`.
4. Zvoľ **Public**. Je to zadarmo bez obmedzení. Token bude aj tak skrytý, viditeľné budú len nastavenia hľadania.
   *(Ak zvolíš Private, v kroku 4 zmeň `*/10` na `*/30`, inak minieš bezplatný limit.)*
5. Zaškrtni **Add a README file** → **Create repository**.

## Krok 3 – Nahraj súbory (3 min)

1. V repozitári klikni **Add file → Upload files**.
2. Nahraj tieto 3 súbory: `monitor.py`, `okresy.py`, `config.toml`.
3. Dole klikni **Commit changes**.

## Krok 4 – Pridaj automatické spúšťanie (2 min)

1. **Add file → Create new file**.
2. Do názvu súboru napíš presne: `.github/workflows/monitor.yml`
   (lomky samé vytvoria priečinky).
3. Do obsahu vlož celý text zo súboru `monitor.yml`.
4. **Commit changes**.

## Krok 5 – Vlož token a chat_id ako tajomstvá (2 min)

1. V repozitári **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `TELEGRAM_TOKEN`, Secret: token z kroku 1 → **Add secret**.
3. Znova **New repository secret**. Name: `TELEGRAM_CHAT_ID`, Secret: číslo z @userinfobot → **Add secret**.

## Krok 5b – E-maily (voliteľné, 3 min)

Ak chceš upozornenia aj na e-mail (alebo namiesto Telegramu):

1. Google účet musí mať zapnuté **dvojstupňové overenie**: myaccount.google.com → Zabezpečenie → Dvojstupňové overenie.
2. Otvor **myaccount.google.com/apppasswords** → názov napr. *Realitny monitor* → **Vytvoriť**.
3. Google ukáže **16-miestne heslo aplikácie** (napr. `abcd efgh ijkl mnop`). Skopíruj ho. Toto heslo nie je tvoje bežné heslo a kedykoľvek ho tam aj zrušíš.
4. V GitHube (Settings → Secrets and variables → Actions) pridaj:
   - `EMAIL_USER` = tvoj Gmail (napr. juraj.mackin@gmail.com)
   - `EMAIL_APP_PASSWORD` = to 16-miestne heslo
   - `EMAIL_TO` = *(voliteľné)* iná adresa, kam to má chodiť. Viac adries oddeľ čiarkou.

Z každej kontroly príde **najviac 1 e-mail** so všetkými novými inzerátmi, zoradenými podľa okresov, so súkromníkmi navrchu a s klikateľnými odkazmi. Ak chceš len e-mail, Telegram secrets jednoducho nepridávaj.

## Predaj a nájom oddelene

Monitor sleduje **predaj aj prenájom bytov** na celom západnom Slovensku a nikdy ich nemieša:
- 🏠 **PREDAJ**: vlastné správy, vlastné súhrny, vlastné e-maily (predmet začína `[PREDAJ]`)
- 🔑 **NÁJOM**: vlastné správy, vlastné súhrny s cenou za mesiac, vlastné e-maily (predmet začína `[NÁJOM]`)

**Chceš ich mať v dvoch rôznych Telegram chatoch?** Odporúčam to, je to najprehľadnejšie.
1. V Telegrame vytvor 2 skupiny, napr. *Reality – Predaj* a *Reality – Nájom*, a do oboch pridaj svojho bota **@juraj_reality_bot**.
2. Do každej skupiny pridaj aj **@userinfobot**. Napíše ti Id skupiny (záporné číslo, napr. `-1001234567890`). Potom ho zo skupiny môžeš odstrániť.
3. Do GitHub Secrets pridaj `TELEGRAM_CHAT_ID_PREDAJ` a `TELEGRAM_CHAT_ID_NAJOM` s týmito číslami.

Bez nich ide všetko do tvojho bežného chatu, ale stále oddelene označené 🏠 / 🔑.

**Rôzne cenové limity:** v `config.toml` → `[nastavenia.predaj]` a `[nastavenia.najom]` (napr. nájom do 900 €).

## Krok 6 – Test (2 min)

1. Hore záložka **Actions**. Ak sa pýta, klikni **I understand… enable them**.
2. Vľavo **Realitny monitor** → vpravo **Run workflow** → režim **test** → **Run workflow**.
3. Do minúty by ti mala prísť na Telegram správa **„✅ testovacia správa“** (a ak si nastavil e-mail, aj testovací e-mail).
4. Klikni na beh → **kontrola** → **Kontrola inzerátov**. Uvidíš, koľko inzerátov našiel na každom portáli a pri prvých dvoch aj okres, cenu a predajcu.

**Ak niekde vypíše „0 inzerátov“ alebo chybu (napr. 403)**, sprav screenshot a pošli mi ho, doladíme to.

## Krok 7 – Hotovo

Od teraz to beží samo každých ~10 minút. Prvá automatická kontrola si len zapamätá súčasné inzeráty, upozornenia chodia na tie, ktoré pribudnú potom.

---

## Úpravy neskôr (aj z mobilu)

V repozitári klikni na `config.toml` → ikona ceruzky ✏️ → uprav → **Commit changes**. Prejaví sa pri ďalšej kontrole.

- **Ďalšie portály:** v prehliadači nastav na portáli byty, 4 západné kraje a zoradenie od najnovších, skopíruj adresu do `url = "..."` pri danom portáli.
- **Len niektoré okresy:** `okresy = ["Senec", "Pezinok", "Bratislava"]`.
- **Len súkromníci:** `iba_sukromnici = true`.
- **Cena:** `cena_do = 250000`.

## Dobré vedieť
- GitHub spustenie niekedy posunie o pár minút, pri vyťažení aj viac. Na „byť prvý“ to stačí, nie je to však na sekundu presné.
- Pamäť videných inzerátov sa ukladá do repozitára (súbor `videne.db`). V histórii preto pribúdajú automatické záznamy „pamäť monitora“, to je v poriadku.
- Niektoré portály môžu požiadavky z GitHubu blokovať. To ukáže test v kroku 6.
- Zastaviť: **Actions → Realitny monitor → ⋯ → Disable workflow**.
- Facebook (Marketplace, skupiny) monitor nepokrýva, vyžaduje prihlásenie.
