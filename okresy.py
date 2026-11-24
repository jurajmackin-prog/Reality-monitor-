"""
Určenie okresu z textu inzerátu.

Poradie (od najspoľahlivejšieho):
  1. výslovne „okres X“ alebo „Bratislava I–V“ v texte
  2. PSČ v texte
  3. mestská časť Bratislavy (Petržalka, Ružinov...)
  4. názov obce v nadpise
  5. názov obce v texte

Zoznam obcí/PSČ/okresov sa pri prvom spustení stiahne z GeoNames
(voľne dostupné dáta) do súboru obce_sk.tsv.
"""
import io
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import requests

GEONAMES_URL = "https://download.geonames.org/export/zip/SK.zip"
DATA_FILE = Path(__file__).resolve().parent / "obce_sk.tsv"

ZAPAD = {
    "Bratislavský kraj": ["Bratislava I", "Bratislava II", "Bratislava III", "Bratislava IV",
                          "Bratislava V", "Malacky", "Pezinok", "Senec"],
    "Trnavský kraj": ["Dunajská Streda", "Galanta", "Hlohovec", "Piešťany", "Senica",
                      "Skalica", "Trnava"],
    "Nitriansky kraj": ["Komárno", "Levice", "Nitra", "Nové Zámky", "Šaľa", "Topoľčany",
                        "Zlaté Moravce"],
    "Trenčiansky kraj": ["Bánovce nad Bebravou", "Ilava", "Myjava", "Nové Mesto nad Váhom",
                         "Partizánske", "Považská Bystrica", "Prievidza", "Púchov", "Trenčín"],
}
OKRES_KRAJ = {o: k for k, okresy in ZAPAD.items() for o in okresy}
OKRES_KRAJ["Bratislava"] = "Bratislavský kraj"

BA_CASTI = {
    "Staré Mesto": "Bratislava I",
    "Ružinov": "Bratislava II", "Vrakuňa": "Bratislava II", "Podunajské Biskupice": "Bratislava II",
    "Prievoz": "Bratislava II", "Trnávka": "Bratislava II",
    "Nové Mesto": "Bratislava III", "Rača": "Bratislava III", "Vajnory": "Bratislava III",
    "Kramáre": "Bratislava III",
    "Karlova Ves": "Bratislava IV", "Dúbravka": "Bratislava IV", "Lamač": "Bratislava IV",
    "Devínska Nová Ves": "Bratislava IV", "Devín": "Bratislava IV",
    "Záhorská Bystrica": "Bratislava IV",
    "Petržalka": "Bratislava V", "Jarovce": "Bratislava V", "Rusovce": "Bratislava V",
    "Čunovo": "Bratislava V",
}

PSC_RE = re.compile(r"(?<![\d.,])(\d{3})[  ]?(\d{2})(?![\d.,])")


def norm(s):
    """bez diakritiky, zachová veľké/malé písmená"""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def clean_okres(name):
    name = re.sub(r"^(okres|district)\s+", "", name.strip(), flags=re.I)
    return re.sub(r"\s+(district|okres)$", "", name, flags=re.I).strip()


def download_data(log=print):
    try:
        log("Sťahujem zoznam obcí a PSČ (GeoNames, jednorazovo)...")
        r = requests.get(GEONAMES_URL, timeout=60)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            DATA_FILE.write_bytes(z.read("SK.txt"))
        log("  Hotovo.")
        return True
    except Exception as e:  # noqa
        log(f"  Nepodarilo sa stiahnuť zoznam obcí ({e}). Okres sa určí len z textu „okres X“.")
        return False


class Lokator:
    def __init__(self, log=print):
        self.psc = {}
        self.obce = {}
        if not DATA_FILE.exists():
            download_data(log)
        if DATA_FILE.exists():
            self._load()
        # okresné mestá a mestské časti BA vždy (aj bez stiahnutých dát)
        for okres in OKRES_KRAJ:
            if not okres.startswith("Bratislava "):
                self.obce.setdefault(norm(okres), okres)
        for cast, okres in BA_CASTI.items():
            self.obce[norm(cast)] = okres
        self.obce[norm("Bratislava")] = "Bratislava"

        names = sorted(self.obce, key=len, reverse=True)
        self._obce_re = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, names)) + r")(?!\w)")
        okres_names = sorted({norm(o) for o in set(self.obce.values()) | set(OKRES_KRAJ)},
                             key=len, reverse=True)
        self._okres_re = re.compile(
            r"(?i)okres(?:e|u|om)?\s*:?\s*(" + "|".join(map(re.escape, okres_names)) + r")(?![\w])"
        )
        self._ba_re = re.compile(r"(?i)Bratislava[ \-–]*(I{1,3}|IV|V)(?![\w])")
        self._okres_by_norm = {norm(o).lower(): o for o in set(self.obce.values()) | set(OKRES_KRAJ)}

    def _load(self):
        psc_votes = defaultdict(Counter)
        name_okresy = defaultdict(set)
        for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
            p = line.split("\t")
            if len(p) < 6:
                continue
            psc = re.sub(r"\D", "", p[1])
            place = p[2].strip()
            okres = clean_okres(p[5]) or clean_okres(p[3])
            if not okres:
                continue
            if psc:
                psc_votes[psc][okres] += 1
            if place:
                name_okresy[norm(place)].add(okres)
        self.psc = {k: v.most_common(1)[0][0] for k, v in psc_votes.items()}
        for name, okresy in name_okresy.items():
            if len(okresy) == 1:
                self.obce[name] = next(iter(okresy))
            elif all(o.startswith("Bratislava") for o in okresy):
                self.obce[name] = "Bratislava"
            else:  # rovnaký názov vo viacerých okresoch → uprednostni západ, ak je jednoznačný
                west = [o for o in okresy if o in OKRES_KRAJ]
                if len(west) == 1:
                    self.obce[name] = west[0]

    def kraj(self, okres):
        return OKRES_KRAJ.get(okres, "")

    def najdi(self, nadpis="", text=""):
        """Vráti názov okresu alebo ''."""
        n_title, n_text = norm(nadpis or ""), norm(text or "")
        both = n_title + "\n" + n_text

        m = self._ba_re.search(both)
        if m:
            return f"Bratislava {m.group(1).upper()}"
        m = self._okres_re.search(both)
        if m:
            return self._okres_by_norm.get(m.group(1).lower(), m.group(1))
        for m in PSC_RE.finditer(both):
            okres = self.psc.get(m.group(1) + m.group(2))
            if okres:
                return okres
        for src in (n_title, n_text):
            for m in self._obce_re.finditer(src):
                okres = self.obce.get(m.group(1))
                if okres and okres != "Bratislava":
                    return okres
            # samotná „Bratislava“ až keď nie je nič presnejšie
            if self._obce_re.search(src) and "Bratislava" in src:
                return "Bratislava"
        return ""


def okres_vyhovuje(okres, povolene):
    """'Bratislava' v nastaveniach zahŕňa Bratislava I–V."""
    if not povolene:
        return True
    for p in povolene:
        if okres == p or okres.startswith(p + " ") or (okres == "Bratislava" and p.startswith("Bratislava")):
            return True
    return False
