
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / "static" / "images"
ROWS_API = "https://datasets-server.huggingface.co/rows"
IMAGE_DATASET = "benitomartin/fashion-product-images-small-384x512"

# (gender, article type) -> how many products to pick
QUOTAS = {
    ("Men", "Shirts"): 6, ("Men", "Tshirts"): 6, ("Men", "Jeans"): 4, ("Men", "Trousers"): 3,
    ("Men", "Kurtas"): 4, ("Men", "Jackets"): 2, ("Men", "Casual Shoes"): 4,
    ("Men", "Formal Shoes"): 3, ("Men", "Sports Shoes"): 3, ("Men", "Watches"): 3,
    ("Women", "Kurtas"): 6, ("Women", "Dresses"): 6, ("Women", "Tops"): 6, ("Women", "Sarees"): 4,
    ("Women", "Jeans"): 3, ("Women", "Heels"): 4, ("Women", "Flats"): 3, ("Women", "Handbags"): 4,
    ("Women", "Watches"): 2, ("Women", "Earrings"): 2,
    ("Unisex", "Sunglasses"): 3, ("Unisex", "Backpacks"): 3,
}

PRICE_RANGES = {
    "Shirts": (799, 2499), "Tshirts": (399, 1299), "Jeans": (1199, 2999), "Trousers": (999, 2499),
    "Kurtas": (599, 2199), "Jackets": (1999, 4999), "Dresses": (899, 2999), "Tops": (499, 1499),
    "Sarees": (1299, 4999), "Casual Shoes": (1299, 3499), "Formal Shoes": (1799, 3999),
    "Sports Shoes": (1999, 4999), "Heels": (999, 2999), "Flats": (599, 1799),
    "Handbags": (999, 3499), "Watches": (1499, 6999), "Earrings": (199, 799),
    "Sunglasses": (799, 2499), "Backpacks": (899, 2499),
}

CLOTHING = {"Shirts", "Tshirts", "Jeans", "Trousers", "Kurtas", "Jackets", "Dresses", "Tops"}
FOOTWEAR = {"Casual Shoes", "Formal Shoes", "Sports Shoes", "Heels", "Flats"}


def pick_products(df, rng):
    """Pick the quota for each group, preferring colours not yet used in that group."""
    picked = []
    for (gender, article), count in QUOTAS.items():
        group = df[(df.gender == gender) & (df.articleType == article)]
        rows = list(group.itertuples())
        rng.shuffle(rows)
        seen_colours, chosen = set(), []
        for row in rows:
            if row.baseColour not in seen_colours:
                chosen.append(row)
                seen_colours.add(row.baseColour)
            if len(chosen) == count:
                break
        picked.extend(chosen)
    return picked


def sizes_for(gender, article):
    if article in CLOTHING:
        return ["S", "M", "L", "XL", "XXL"]
    if article in FOOTWEAR:
        return ["6", "7", "8", "9", "10"] if gender == "Men" else ["4", "5", "6", "7", "8"]
    return ["One Size"]


def download_image(row_index, product_id):
    """Fetch the 384x512 photo for a dataset row. Returns False if the row doesn't match."""
    if (IMAGE_DIR / f"{product_id}.jpg").exists():
        return True
    query = urllib.parse.urlencode({
        "dataset": IMAGE_DATASET, "config": "default", "split": "train",
        "offset": row_index, "length": 1,
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{ROWS_API}?{query}", timeout=30) as response:
                row = json.load(response)["rows"][0]["row"]
            if row["id"] != product_id:
                return False
            with urllib.request.urlopen(row["image"]["src"], timeout=30) as response:
                (IMAGE_DIR / f"{product_id}.jpg").write_bytes(response.read())
            return True
        except Exception as error:
            print(f"  retrying {product_id}: {error}")
            time.sleep(3 * (attempt + 1))
    return False


def main():
    rng = random.Random(61)
    df = pd.read_parquet(sys.argv[1], columns=[
        "id", "gender", "subCategory", "articleType", "baseColour", "season", "usage",
        "productDisplayName",
    ]).dropna()
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    catalog = []
    for row in pick_products(df, rng):
        if not download_image(row.Index, row.id):
            print(f"skipped {row.id} (no image)")
            continue
        low, high = PRICE_RANGES[row.articleType]
        sizes = sizes_for(row.gender, row.articleType)
        sold_out = rng.random() < 0.08
        levels = [1, 2, 3, 5, 8, 12] if len(sizes) == 1 else [0, 0, 1, 2, 3, 5, 8, 12]
        stock = {size: 0 if sold_out else rng.choice(levels) for size in sizes}
        catalog.append({
            "id": int(row.id),
            "name": row.productDisplayName.strip(),
            "gender": row.gender,
            "category": row.subCategory,
            "type": row.articleType,
            "colour": row.baseColour,
            "occasion": row.usage,
            "season": row.season,
            "price": low + 100 * rng.randrange((high - low) // 100 + 1),
            "rating": round(rng.uniform(3.6, 4.9), 1),
            "stock": stock,
            "image": f"/static/images/{int(row.id)}.jpg",
        })
        print(f"{len(catalog):3d}  {row.productDisplayName}")
        time.sleep(0.2)

    out = ROOT / "data" / "catalog.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"wrote {len(catalog)} products to {out}")


if __name__ == "__main__":
    main()
