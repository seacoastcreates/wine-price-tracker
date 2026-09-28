"""Growing regions: a gazetteer that maps words in a wine's name to a region with vineyard
coordinates, so each wine can be joined to its region's growing-season weather.

Coordinates are approximate centroids of each region's vineyard area (weather grids are ~11-25 km,
so this precision is enough). Hemisphere decides the growing season: Apr-Oct in the north,
Oct-Apr in the south (a southern vintage year is the year of its harvest).
"""

import re
import unicodedata

# region -> (latitude, longitude, hemisphere)
REGIONS: dict[str, tuple[float, float, str]] = {
    "Napa Valley": (38.43, -122.35, "N"),
    "Sonoma": (38.58, -122.85, "N"),
    "Lodi": (38.13, -121.27, "N"),
    "California Central Valley": (37.00, -120.50, "N"),
    "Paso Robles": (35.63, -120.69, "N"),
    "Santa Barbara": (34.65, -120.20, "N"),
    "Monterey": (36.30, -121.30, "N"),
    "Central Coast": (35.30, -120.60, "N"),
    "Washington": (46.25, -119.50, "N"),
    "Oregon": (45.20, -123.10, "N"),
    "Finger Lakes": (42.60, -76.90, "N"),
    "Lake Erie": (42.10, -80.00, "N"),
    "Marlborough": (-41.50, 173.95, "S"),
    "Hawke's Bay": (-39.60, 176.80, "S"),
    "Barossa": (-34.53, 138.95, "S"),
    "McLaren Vale": (-35.20, 138.55, "S"),
    "South Australia": (-34.60, 138.80, "S"),
    "Riverland (South Eastern Australia)": (-34.20, 140.80, "S"),
    "Mendoza": (-33.00, -68.80, "S"),
    "Chile Central Valley": (-34.60, -71.20, "S"),
    "Western Cape": (-33.93, 18.86, "S"),
    "Champagne": (49.05, 4.00, "N"),
    "Bordeaux": (44.90, -0.50, "N"),
    "Burgundy": (47.05, 4.85, "N"),
    "Beaujolais": (46.15, 4.65, "N"),
    "Rhone": (44.30, 4.80, "N"),
    "Provence": (43.45, 6.20, "N"),
    "Loire": (47.30, 1.50, "N"),
    "Alsace": (48.10, 7.30, "N"),
    "Languedoc-Roussillon": (43.40, 3.20, "N"),
    "Tuscany": (43.40, 11.20, "N"),
    "Piedmont": (44.60, 7.95, "N"),
    "Veneto": (45.70, 11.80, "N"),
    "Trentino-Alto Adige": (46.40, 11.30, "N"),
    "Friuli": (46.00, 13.20, "N"),
    "Abruzzo": (42.35, 14.00, "N"),
    "Puglia": (40.50, 17.80, "N"),
    "Sicily": (37.80, 13.50, "N"),
    "Rioja": (42.45, -2.45, "N"),
    "Ribera del Duero": (41.65, -3.80, "N"),
    "Rueda / Toro": (41.40, -4.95, "N"),
    "Priorat": (41.20, 0.80, "N"),
    "Penedes (Cava)": (41.35, 1.70, "N"),
    "Rias Baixas": (42.40, -8.70, "N"),
    "Douro": (41.15, -7.60, "N"),
    "Vinho Verde": (41.70, -8.40, "N"),
    "Mosel": (49.90, 6.95, "N"),
    "Rheinhessen / Pfalz": (49.60, 8.15, "N"),
    "Rheingau": (50.00, 8.00, "N"),
}

# keyword (as it appears in names, lower case, no accents) -> region. Longer keywords win.
KEYWORDS: dict[str, str] = {
    **{k: "Napa Valley" for k in ["napa", "oakville", "rutherford", "stags leap", "howell mountain", "carneros",
                                  "st helena", "saint helena", "calistoga", "mount veeder", "spring mountain",
                                  "atlas peak", "coombsville", "yountville", "diamond mountain"]},
    **{k: "Sonoma" for k in ["sonoma", "russian river", "alexander valley", "dry creek", "knights valley",
                             "chalk hill", "bennett valley", "north coast"]},
    "lodi": "Lodi",
    "california": "California Central Valley",
    **{k: "Paso Robles" for k in ["paso robles", "adelaida"]},
    **{k: "Santa Barbara" for k in ["santa barbara", "santa rita hills", "sta rita hills", "santa maria",
                                    "santa ynez", "happy canyon", "ballard canyon"]},
    **{k: "Monterey" for k in ["monterey", "arroyo seco", "santa lucia highlands", "chalone"]},
    **{k: "Central Coast" for k in ["central coast", "san luis obispo", "edna valley", "arroyo grande"]},
    **{k: "Washington" for k in ["washington", "columbia valley", "walla walla", "horse heaven", "red mountain",
                                 "yakima", "wahluke"]},
    **{k: "Oregon" for k in ["oregon", "willamette", "dundee hills", "eola amity", "chehalem", "ribbon ridge",
                             "yamhill"]},
    **{k: "Finger Lakes" for k in ["finger lakes", "new york", "seneca lake", "keuka"]},
    **{k: "Lake Erie" for k in ["lake erie", "pennsylvania"]},
    **{k: "Marlborough" for k in ["marlborough", "new zealand", "awatere"]},
    "hawkes bay": "Hawke's Bay",
    **{k: "Barossa" for k in ["barossa", "eden valley"]},
    "mclaren vale": "McLaren Vale",
    **{k: "South Australia" for k in ["south australia", "coonawarra", "clare valley", "adelaide hills",
                                      "langhorne creek"]},
    **{k: "Riverland (South Eastern Australia)" for k in ["south eastern australia", "southeastern australia",
                                                          "australia", "riverland"]},
    **{k: "Mendoza" for k in ["mendoza", "uco valley", "lujan de cuyo", "argentina", "tupungato"]},
    **{k: "Chile Central Valley" for k in ["chile", "maipo", "colchagua", "casablanca", "rapel", "cachapoal",
                                           "curico", "maule", "aconcagua"]},
    **{k: "Western Cape" for k in ["stellenbosch", "western cape", "south africa", "swartland", "paarl",
                                   "franschhoek", "coastal region"]},
    "champagne": "Champagne",
    **{k: "Bordeaux" for k in ["bordeaux", "medoc", "haut medoc", "margaux", "pauillac", "saint julien",
                               "saint estephe", "pessac", "leognan", "graves", "sauternes", "barsac",
                               "saint emilion", "st emilion", "pomerol", "entre deux mers", "blaye",
                               "cotes de bourg", "fronsac", "listrac", "moulis", "lalande de pomerol",
                               "castillon"]},
    **{k: "Burgundy" for k in ["bourgogne", "burgundy", "chablis", "cote de beaune", "cote de nuits",
                               "meursault", "puligny", "chassagne", "gevrey", "nuits saint georges",
                               "pommard", "volnay", "macon", "pouilly fuisse", "santenay", "marsannay",
                               "vosne", "chambolle", "morey saint denis", "aloxe corton", "savigny",
                               "mercurey", "givry", "rully", "saint veran", "vire clesse"]},
    **{k: "Beaujolais" for k in ["beaujolais", "morgon", "fleurie", "moulin a vent", "julienas", "brouilly",
                                 "chiroubles", "saint amour", "chenas", "regnie"]},
    **{k: "Rhone" for k in ["cotes du rhone", "cote du rhone", "chateauneuf", "gigondas", "vacqueyras",
                            "crozes hermitage", "hermitage", "cote rotie", "rhone", "condrieu",
                            "saint joseph", "rasteau", "ventoux", "lirac", "tavel", "cairanne", "luberon",
                            "costieres de nimes", "vinsobres"]},
    **{k: "Provence" for k in ["provence", "bandol", "cotes de provence"]},
    **{k: "Loire" for k in ["sancerre", "vouvray", "muscadet", "pouilly fume", "loire", "chinon", "anjou",
                            "saumur", "touraine", "savennieres", "bourgueil", "menetou"]},
    "alsace": "Alsace",
    **{k: "Languedoc-Roussillon" for k in ["languedoc", "minervois", "corbieres", "pays d oc", "saint chinian",
                                           "roussillon", "faugeres", "picpoul", "limoux", "pic saint loup"]},
    **{k: "Tuscany" for k in ["toscana", "tuscany", "chianti", "brunello", "montalcino", "bolgheri", "maremma",
                              "vino nobile", "montepulciano", "sassicaia", "morellino", "carmignano",
                              "vernaccia"]},
    **{k: "Piedmont" for k in ["piedmont", "piemonte", "barolo", "barbaresco", "langhe", "asti", "alba", "gavi",
                               "roero", "monferrato", "dogliani", "ghemme", "gattinara"]},
    **{k: "Veneto" for k in ["veneto", "prosecco", "valpolicella", "amarone", "soave", "ripasso", "bardolino",
                             "delle venezie", "valdobbiadene", "conegliano", "lugana"]},
    **{k: "Trentino-Alto Adige" for k in ["alto adige", "trentino", "trento", "dolomiti", "sudtirol"]},
    **{k: "Friuli" for k in ["friuli", "collio", "grave del friuli"]},
    **{k: "Abruzzo" for k in ["abruzzo", "montepulciano d abruzzo"]},
    **{k: "Puglia" for k in ["puglia", "salento", "manduria", "apulia"]},
    **{k: "Sicily" for k in ["sicilia", "sicily", "etna", "terre siciliane", "vittoria"]},
    "rioja": "Rioja",
    "ribera del duero": "Ribera del Duero",
    **{k: "Rueda / Toro" for k in ["rueda", "toro", "castilla y leon"]},
    **{k: "Priorat" for k in ["priorat", "montsant"]},
    **{k: "Penedes (Cava)" for k in ["penedes", "cava", "catalunya"]},
    **{k: "Rias Baixas" for k in ["rias baixas", "albarino"]},
    **{k: "Douro" for k in ["douro", "porto", "port"]},
    "vinho verde": "Vinho Verde",
    **{k: "Mosel" for k in ["mosel", "saar", "ruwer"]},
    **{k: "Rheinhessen / Pfalz" for k in ["rheinhessen", "pfalz", "nahe"]},
    "rheingau": "Rheingau",
}
_ORDERED = sorted(KEYWORDS, key=len, reverse=True)
_PATTERNS = [(re.compile(rf"\b{re.escape(k)}\b"), KEYWORDS[k]) for k in _ORDERED]


def normalize(text: str, apostrophe: str = " ") -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’]", apostrophe, text)).strip()


def region_of(description: str) -> str | None:
    """The growing region named in a wine's description, or None if none is recognized.

    Apostrophes are tried both as a space ("d'Abruzzo" -> "d abruzzo") and dropped
    ("Stag's Leap" -> "stags leap"), so keywords can be written either way."""
    names = (normalize(description), normalize(description, apostrophe=""))
    for pattern, region in _PATTERNS:
        if any(pattern.search(n) for n in names):
            return region
    return None
