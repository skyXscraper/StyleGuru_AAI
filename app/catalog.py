import json
import re
from pathlib import Path

CATALOG = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "catalog.json").read_text(encoding="utf-8")
)
BY_ID = {product["id"]: product for product in CATALOG}
PRODUCT_TYPES = sorted({product["type"] for product in CATALOG})
OCCASIONS = sorted({product["occasion"] for product in CATALOG})

MAX_RESULTS = 8
MAX_UNAVAILABLE = 2
MIN_COLOUR_MATCHES = 4

COLOUR_FAMILIES = {
    "blue": ["blue", "navy blue", "navy", "teal", "indigo", "denim"],
    "green": ["green", "olive", "teal", "mint"],
    "red": ["red", "maroon", "wine", "burgundy"],
    "pink": ["pink", "magenta", "rose", "peach"],
    "brown": ["brown", "tan", "beige", "khaki", "cream", "camel"],
    "grey": ["grey", "gray", "grey melange", "silver", "charcoal"],
    "yellow": ["yellow", "mustard", "gold"],
    "white": ["white", "off white", "ivory"],
    "black": ["black"],
    "orange": ["orange", "rust"],
    "purple": ["purple", "lavender", "violet"],
}


def _families(colour):
    return {family for family, names in COLOUR_FAMILIES.items() if colour in names}


def colour_match(wanted, actual):
    """2 = same colour, 1 = same colour family, 0 = different."""
    wanted, actual = wanted.lower().strip(), actual.lower().strip()
    if wanted == actual or wanted in actual.split() or actual in wanted.split():
        return 2
    return 1 if _families(wanted) & _families(actual) else 0


def _best_colour_match(colours, product):
    return max((colour_match(colour, product["colour"]) for colour in colours), default=0)


def _size_to_check(product, requested, profile):
    stock = product["stock"]
    for size in (requested, profile.get("size"), profile.get("shoe_size")):
        if size and str(size).upper() in stock:
            return str(size).upper()
    return "One Size" if "One Size" in stock else None


def _price(amount):
    return f"₹{amount:,}"


def normalise(filters):
    
    def texts(value):
        if not value:
            return []
        return [str(v) for v in (value if isinstance(value, (list, tuple)) else [value]) if v]

    def number(value):
        try:
            return int(float(value)) or None
        except (TypeError, ValueError):
            return None

    size = filters.get("size")
    if isinstance(size, float) and size.is_integer():
        size = int(size)  # a shoe size sent as 8.0

    cleaned = {
        "product_types": [t for t in texts(filters.get("product_types")) if t in PRODUCT_TYPES],
        "gender": filters.get("gender") if filters.get("gender") in ("Men", "Women") else None,
        "colours": texts(filters.get("colours")),
        "occasion": filters.get("occasion") if filters.get("occasion") in OCCASIONS else None,
        "min_price": number(filters.get("min_price")),
        "max_price": number(filters.get("max_price")),
        "size": " ".join(texts(size)).upper() or None,
        "keywords": " ".join(texts(filters.get("keywords"))) or None,
    }
    return {key: value for key, value in cleaned.items() if value}


def search(filters, profile=None):
    
    profile = profile or {}
    notes = []

    gender = filters.get("gender") or profile.get("gender")
    types = filters.get("product_types") or []
    colours = filters.get("colours") or []
    occasion = filters.get("occasion")
    max_price = filters.get("max_price")
    min_price = filters.get("min_price")
    requested_size = filters.get("size")
    keywords = set(re.findall(r"[a-z]+", (filters.get("keywords") or "").lower()))

    disliked = set(profile.get("disliked") or [])
    liked = [BY_ID[i] for i in profile.get("liked") or [] if i in BY_ID]
    liked_types = {p["type"] for p in liked}
    liked_colours = {p["colour"] for p in liked}
    favourite_colours = profile.get("colours") or []
    budget = profile.get("budget")

    candidates = [p for p in CATALOG if p["id"] not in disliked]
    if gender:
        candidates = [p for p in candidates if p["gender"] in (gender, "Unisex")]
    if types:
        candidates = [p for p in candidates if p["type"] in types]
    if min_price:
        candidates = [p for p in candidates if p["price"] >= min_price]
    if max_price:
        within = [p for p in candidates if p["price"] <= max_price]
        if not within and candidates:
            cheapest = min(p["price"] for p in candidates)
            notes.append(f"Nothing under {_price(max_price)}; the cheapest option is {_price(cheapest)}.")
            within = sorted(candidates, key=lambda p: p["price"])[:3]
        candidates = within
    if colours:
        matching = [p for p in candidates if _best_colour_match(colours, p)]
        if len(matching) >= MIN_COLOUR_MATCHES:
            candidates = matching  # otherwise keep other colours too; matches still rank first
        elif candidates and not matching:
            notes.append(f"No {'/'.join(colours)} items match; showing other colours.")

    scored = []
    for product in candidates:
        score = product["rating"] * 0.3
        reasons = []

        match = _best_colour_match(colours, product)
        if match:
            score += 2 * match
            reasons.append(f"{product['colour']} as requested" if match == 2 else f"{product['colour']} is close to your colour")
        if occasion and product["occasion"] == occasion:
            score += 3
            reasons.append(f"{occasion} wear")
        score += min(3, sum(1 for word in keywords if word in product["name"].lower()))
        if max_price and product["price"] <= max_price:
            reasons.append(f"Under {_price(max_price)}")
        elif budget and product["price"] <= budget:
            score += 1
            reasons.append("Within your budget")

        if not match and any(colour_match(c, product["colour"]) == 2 for c in favourite_colours):
            score += 1.5
            reasons.append("One of your favourite colours")
        if product["colour"] in liked_colours or product["type"] in liked_types:
            score += 1
            reasons.append("Similar to items you liked")

        size = _size_to_check(product, requested_size, profile)
        left = product["stock"][size] if size else sum(product["stock"].values())
        if left and size and size != "One Size":
            reasons.append(f"Only {left} left in {size}" if left <= 2 else f"{size} in stock")

        scored.append((score, {
            **product,
            "available": left > 0,
            "size_checked": size,
            "reasons": reasons[:3],
        }))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = [p for _, p in scored if p["available"]][:MAX_RESULTS]
    unavailable = [p for _, p in scored if not p["available"]][:MAX_UNAVAILABLE]

    if not candidates:
        notes.append("No products match these requirements.")
    elif not results:
        notes.append("Matching products exist but are sold out in the shopper's size.")
    return {"results": results, "unavailable": unavailable, "notes": notes}


def featured(gender=None):
    """Top-rated in-stock products for the landing view."""
    in_stock = [
        {**p, "available": True, "size_checked": None, "reasons": []}
        for p in CATALOG
        if any(p["stock"].values()) and (not gender or p["gender"] in (gender, "Unisex"))
    ]
    picks, seen_types = [], set()
    for product in sorted(in_stock, key=lambda p: p["rating"], reverse=True):
        if product["type"] not in seen_types:
            picks.append(product)
            seen_types.add(product["type"])
    return picks[:MAX_RESULTS]
