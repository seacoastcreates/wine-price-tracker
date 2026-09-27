"""Keyword rules that tell wine from spirits/accessories and assign a wine style.

The PLCB price list has no category column, so this is inferred from the description.
"""

import re

SPIRIT = re.compile(
    r"\b(vodka|tequila|mezcal|whiske?y|scotch|bourbon|rye|rum|gin|brandy|cognac|armagnac|liqueur|schnapps|"
    r"cordial|absinthe|grappa|pisco|soju|sake|proof|cocktails?|seltzer|hard cider|moonshine|spirits?|"
    r"vermouth|aperitivo|amaro|bitters|cream liqueur|margarita|mixer|cans?)\b",
    re.I,
)
# "Bourbon Barrel Aged" wines (e.g. 1000 Stories) are still wine.
BARREL_AGED = re.compile(r"\b(bourbon|whiske?y|rum)\s+barrel", re.I)

SPARKLING = re.compile(r"\b(champagne|prosecco|cava|cr[eé]mant|brut|sparkling|spumante|franciacorta|asti|sekt|p[eé]tillant|lambrusco)\b", re.I)
ROSE = re.compile(r"\b(ros[eé]|rosato|rosado|blush|white zinfandel)\b", re.I)
DESSERT = re.compile(r"\b(port|porto|sherry|madeira|marsala|sauternes|tokaji|ice ?wine|late harvest|vin santo|moscatel|dessert)\b", re.I)
WHITE = re.compile(
    r"\b(chardonnay|sauvignon blanc|pinot grigio|pinot gris|riesling|moscato|muscat|albari[nñ]o|chenin|gr[uü]ner|"
    r"viognier|chablis|sancerre|soave|vinho verde|gew[uü]rztraminer|white|blanc|verdejo|vermentino|torront[eé]s|"
    r"pouilly|semillon|fiano|assyrtiko|trebbiano|pecorino|garganega|marsanne|roussanne|muscadet|bianco|branco|blanco)\b",
    re.I,
)
RED = re.compile(
    r"\b(cabernet|merlot|pinot noir|syrah|shiraz|malbec|zinfandel|sangiovese|tempranillo|grenache|garnacha|nebbiolo|"
    r"barolo|barbaresco|chianti|brunello|rioja|ribera|bordeaux|burgundy|bourgogne|c[oô]tes du rh[oô]ne|ch[aâ]teauneuf|"
    r"beaujolais|red|rosso|tinto|rouge|primitivo|montepulciano|nero d'avola|carmen[eè]re|petite sirah|petit verdot|"
    r"cabernet franc|gamay|amarone|valpolicella|barbera|dolcetto|aglianico|mourv[eè]dre|monastrell|pinotage|"
    r"super tuscan|toscana|claret|meritage|m[eé]doc|margaux|pauillac|saint-?[eé]milion|pomerol|napa|saint-? ?julien|"
    r"saint-? ?est[eè]phe|pessac|graves|haut-m[eé]doc|douro|mendoza|priorat|toro|bierzo|ch[aâ]teau|domaine|chateau)\b",
    re.I,
)
VINTAGE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
WINE_SIZE = re.compile(r"^(187|250|375|500|750|1000|1500|3000|5000) ML$")


def style_of(desc: str) -> str | None:
    """Wine style for a description, or None if it doesn't look like wine."""
    if SPIRIT.search(desc) and not BARREL_AGED.search(desc):
        return None
    for style, pat in (("sparkling", SPARKLING), ("rose", ROSE), ("dessert", DESSERT), ("white", WHITE), ("red", RED)):
        if pat.search(desc):
            return style
    # A vintage year on a non-spirit is a wine; unlabeled vintage wines are overwhelmingly red.
    return "red" if VINTAGE.search(desc) else None


def is_wine(desc: str, size: str) -> bool:
    return bool(WINE_SIZE.match(size)) and style_of(desc) is not None


def tier_of(price: float) -> str:
    return "everyday" if price < 25 else "premium" if price < 75 else "luxury"


def product_key(desc: str, size: str) -> str:
    """Identity of a wine across vintages: the description minus vintage/NV, plus bottle size."""
    base = VINTAGE.sub("", re.sub(r"\bnonvintage\b", "", desc, flags=re.I))
    base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    size_slug = re.sub(r"[^a-z0-9]+", "", size.lower())
    return f"{base}-{size_slug}"
