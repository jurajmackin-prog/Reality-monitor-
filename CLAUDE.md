# Realitný monitor – poznámky pre Claude

- Majiteľ: Juraj (komunikácia po slovensky, často z mobilu).
- Beží na GitHub Actions (`.github/workflows/monitor.yml`), cron každých 10 min, `python monitor.py --raz`.
- Pamäť videných inzerátov: `videne.db` (SQLite) – workflow ju commituje späť do repozitára. Nemazať.
- `obce_sk.tsv` = GeoNames PSČ/obce/okresy, stiahne sa automaticky pri prvom behu.
- Nastavenia pre používateľa sú v `config.toml` (portály = URL vyhľadávaní). Tajomstvá (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_TO) sú v GitHub Secrets – nikdy ich nepísať do súborov.
- `okresy.py` = určenie okresu z textu inzerátu.
- Pri zmenách over syntax a ak sa dá, otestuj `python monitor.py --test`.
- Každé [[hladanie]] má `typ = "predaj" | "najom"`; predaj a nájom sa posielajú oddelene (vlastné súhrny, e-maily, voliteľne vlastné chaty TELEGRAM_CHAT_ID_PREDAJ / _NAJOM). Ceny per typ v [nastavenia.predaj] / [nastavenia.najom].
- URL s `{druh}` sa rozbalí podľa `druhy` v [nastavenia] (byt, dom, pozemok, chata, garaz, ...) – Bazoš kategórie reality.bazos.sk/predam/<druh>/.
