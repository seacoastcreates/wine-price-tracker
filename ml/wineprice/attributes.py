"""Wine attributes parsed from names: brand (producer), grape variety, and classification.

Used at load time to populate the `wines` table, so training and serving read the same columns.
"""

import re
import unicodedata

# keyword (normalized) -> canonical grape. Longer keywords win.
GRAPES = {
    "cabernet sauvignon": "Cabernet Sauvignon", "cabernet": "Cabernet Sauvignon", "cab sauv": "Cabernet Sauvignon",
    "cabernet franc": "Cabernet Franc", "merlot": "Merlot", "pinot noir": "Pinot Noir", "syrah": "Syrah",
    "shiraz": "Syrah", "zinfandel": "Zinfandel", "primitivo": "Zinfandel", "malbec": "Malbec",
    "sangiovese": "Sangiovese", "nebbiolo": "Nebbiolo", "tempranillo": "Tempranillo", "grenache": "Grenache",
    "garnacha": "Grenache", "petite sirah": "Petite Sirah", "carmenere": "Carmenere", "pinotage": "Pinotage",
    "barbera": "Barbera", "montepulciano d abruzzo": "Montepulciano", "nero d avola": "Nero d'Avola",
    "gamay": "Gamay", "mourvedre": "Mourvedre", "monastrell": "Mourvedre", "petit verdot": "Petit Verdot",
    "aglianico": "Aglianico", "corvina": "Corvina", "touriga": "Touriga Nacional",
    "chardonnay": "Chardonnay", "sauvignon blanc": "Sauvignon Blanc", "fume blanc": "Sauvignon Blanc",
    "pinot grigio": "Pinot Gris", "pinot gris": "Pinot Gris", "riesling": "Riesling", "moscato": "Muscat",
    "muscat": "Muscat", "chenin blanc": "Chenin Blanc", "gruner veltliner": "Gruner Veltliner",
    "albarino": "Albarino", "viognier": "Viognier", "gewurztraminer": "Gewurztraminer", "verdejo": "Verdejo",
    "vermentino": "Vermentino", "semillon": "Semillon", "torrontes": "Torrontes", "glera": "Glera",
    "red blend": "Red Blend", "white blend": "White Blend", "meritage": "Bordeaux Blend",
}
# Appellations whose grape is implied by law or custom (used when no grape is named).
IMPLIED = {
    "barolo": "Nebbiolo", "barbaresco": "Nebbiolo", "langhe nebbiolo": "Nebbiolo", "chianti": "Sangiovese",
    "brunello": "Sangiovese", "vino nobile": "Sangiovese", "rioja": "Tempranillo", "ribera del duero": "Tempranillo",
    "chablis": "Chardonnay", "pouilly fuisse": "Chardonnay", "meursault": "Chardonnay", "puligny": "Chardonnay",
    "chassagne": "Chardonnay", "sancerre": "Sauvignon Blanc", "pouilly fume": "Sauvignon Blanc",
    "vouvray": "Chenin Blanc", "beaujolais": "Gamay", "morgon": "Gamay", "fleurie": "Gamay",
    "chateauneuf": "Grenache", "cotes du rhone": "Grenache", "gigondas": "Grenache", "cote rotie": "Syrah",
    "hermitage": "Syrah", "prosecco": "Glera", "champagne": "Champagne Blend", "cava": "Cava Blend",
    "amarone": "Corvina", "valpolicella": "Corvina", "soave": "Garganega", "port": "Port Blend",
    "porto": "Port Blend", "sauternes": "Semillon",
    **{k: "Bordeaux Blend" for k in ["bordeaux", "medoc", "margaux", "pauillac", "saint julien", "saint estephe",
                                     "pessac", "graves", "saint emilion", "st emilion", "pomerol", "haut medoc"]},
}
# Most prestigious label first.
CLASSIFICATIONS = [
    ("Grand Cru Classe", r"\b(premier grand cru classe|1er grand cru classe|grand cru classe|cru classe|"
                         r"premier cru classe|1er cru classe|deuxieme cru|second growth|first growth)\b"),
    ("Grand Cru", r"\bgrand cru\b"),
    ("Premier Cru", r"\b(premier cru|1er cru)\b"),
    ("Gran Reserva", r"\bgran reserva\b"),
    ("Reserva / Riserva", r"\b(reserva|riserva)\b"),
    ("DOCG", r"\b(docg|barolo|barbaresco|brunello|chianti classico|amarone|vino nobile)\b"),
    ("Reserve", r"\b(reserve|private reserve|special selection|grand vin)\b"),
    ("Single Vineyard", r"\b(vineyard|vigna|clos|lieu dit)\b"),
]
_CLASS_RES = [(name, re.compile(p)) for name, p in CLASSIFICATIONS]

PREFIXES = {"chateau", "domaine", "tenuta", "bodegas", "bodega", "castello", "weingut", "maison", "cantina",
            "cantine", "caves", "cave", "villa", "quinta", "casa", "vina", "vinedos", "poderi", "podere",
            "fattoria", "marchesi", "clos", "mas", "herdade", "familia", "famille"}
PARTICLES = {"the", "la", "le", "les", "el", "il", "lo", "de", "du", "des", "di", "del", "della", "dei", "d",
             "l", "san", "santa", "st", "saint", "ste", "von", "van"}
STOP = {"by", "cellars", "cellar", "vineyards", "vineyard", "winery", "wines", "wine", "estate", "estates",
        "family", "company", "co", "red", "white", "rose", "brut", "sparkling", "reserve", "reserva", "riserva",
        "grand", "cru", "classe", "nonvintage", "blend", "extra", "dry", "sweet", "limited", "edition", "old",
        "vine", "vines", "single"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’]", " ", text))).strip()


def _first_match(name: str, table: dict[str, str]) -> str | None:
    for k in sorted(table, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", name):
            return table[k]
    return None


def grape_of(description: str) -> str | None:
    n = normalize(description)
    return _first_match(n, GRAPES) or _first_match(n, IMPLIED)


def classification_of(description: str) -> str | None:
    n = normalize(description)
    return next((name for name, rx in _CLASS_RES if rx.search(n)), None)


def brand_of(description: str, extra_stop: set[str] = frozenset()) -> str | None:
    """Producer/brand: leading prefixes and particles, the first distinctive word, and a second
    distinctive word unless it names a grape, region, style or generic word ("Cellars")."""
    tokens = re.sub(r"\b(19|20)\d{2}\b", " ", normalize(description)).split()
    grape_words = {w for k in (*GRAPES, *IMPLIED) for w in k.split()}
    stop = STOP | grape_words | set(extra_stop)
    out, content = [], 0
    for tok in tokens:
        if content == 0 and (tok in PREFIXES or tok in PARTICLES):
            out.append(tok)
            continue
        if content == 1 and tok in PARTICLES:
            out.append(tok)
            continue
        if content == 0:
            out.append(tok)  # the first distinctive word is always part of the brand
            content = 1
            continue
        if tok in stop or tok.isdigit():
            break
        out.append(tok)
        break
    while out and out[-1] in PARTICLES:
        out.pop()
    return " ".join(out) or None
