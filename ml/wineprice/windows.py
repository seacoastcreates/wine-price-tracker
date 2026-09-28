"""Heuristic drinking windows: years after the vintage when a wine is typically at its best.

Critics' per-wine drinking windows are copyrighted and not available as open data, so this is a
rule-of-thumb table by region, style, and price tier, built from widely published aging guidance
(e.g. classed-growth Bordeaux needs a decade; Marlborough Sauvignon Blanc is best young). It is a
feature for the model, not advice, and it is tested in the ablation like any other feature.
"""

# (start, end) years after vintage, by red region group and tier.
RED = {
    "bordeaux": {"luxury": (10, 35), "premium": (5, 15), "everyday": (1, 6)},
    "burgundy": {"luxury": (8, 25), "premium": (4, 12), "everyday": (1, 5)},
    "piedmont": {"luxury": (8, 25), "premium": (5, 15), "everyday": (1, 5)},
    "rhone": {"luxury": (6, 20), "premium": (3, 10), "everyday": (1, 4)},
    "tuscany": {"luxury": (6, 20), "premium": (4, 12), "everyday": (1, 5)},
    "iberia": {"luxury": (6, 20), "premium": (3, 12), "everyday": (1, 5)},
    "new_world_cab": {"luxury": (6, 20), "premium": (3, 12), "everyday": (1, 4)},
    "australia": {"luxury": (8, 25), "premium": (3, 12), "everyday": (1, 4)},
    "cool_pinot": {"luxury": (5, 15), "premium": (3, 10), "everyday": (1, 4)},
    "default": {"luxury": (5, 15), "premium": (2, 8), "everyday": (0, 4)},
}
RED_GROUP = {
    "Bordeaux": "bordeaux", "Burgundy": "burgundy", "Beaujolais": "cool_pinot", "Piedmont": "piedmont",
    "Rhone": "rhone", "Tuscany": "tuscany", "Rioja": "iberia", "Ribera del Duero": "iberia", "Priorat": "iberia",
    "Douro": "iberia", "Rueda / Toro": "iberia", "Napa Valley": "new_world_cab", "Sonoma": "new_world_cab",
    "Washington": "new_world_cab", "Paso Robles": "new_world_cab", "Barossa": "australia",
    "McLaren Vale": "australia", "South Australia": "australia", "Oregon": "cool_pinot",
    "Santa Barbara": "cool_pinot", "Marlborough": "cool_pinot",
}
AGEWORTHY_WHITE_REGIONS = {"Burgundy", "Mosel", "Rheingau", "Rheinhessen / Pfalz", "Alsace", "Loire"}


def drinking_window(region: str | None, style: str, tier: str) -> tuple[int, int]:
    """Typical (start, end) of the drinking window, in years after the vintage."""
    if style == "red":
        return RED[RED_GROUP.get(region or "", "default")][tier]
    if style == "white":
        if region in AGEWORTHY_WHITE_REGIONS and tier != "everyday":
            return (3, 15) if tier == "luxury" else (2, 10)
        return (1, 6) if tier == "luxury" else (0, 3)
    if style == "sparkling":
        # Vintage-dated sparkling only (non-vintage wines get no window).
        return {"luxury": (5, 20), "premium": (3, 12), "everyday": (1, 4)}[tier]
    if style == "dessert":
        if region in ("Bordeaux", "Douro"):  # Sauternes, vintage Port
            return (8, 40)
        return (2, 15)
    return (0, 2)  # rose
