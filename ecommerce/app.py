import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any, Optional

import pandas as pd # type: ignore
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user # type: ignore

from forms import LoginForm, SignupForm
from models import Interaction, User, db # type: ignore
from recommenders.collab import CollabRecommender
from recommenders.content_based import ContentRecommender

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "your-secret-key-here-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///site.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app) # type: ignore
login_manager = LoginManager(app) # type: ignore
login_manager.login_view = "login" # type: ignore

SITE_NAME = "ShadowMarket"
PLACEHOLDER_IMAGE_PATH = "/static/images/product-placeholder.svg"
FREE_SHIPPING_THRESHOLD = 150.0
STANDARD_SHIPPING_FEE = 12.0
ESTIMATED_TAX_RATE = 0.08
HOME_HERO_FAMILY_ID = "electronics-macbook-air-m3"
RESULTS_PER_PAGE = 12
RECENTLY_VIEWED_LIMIT = 8
HOME_RECOMMENDATION_LIMIT = 4
RECOMMENDATION_POOL_SIZE = 24

CATEGORY_FALLBACK_PHOTO_IDS = {
    "Mobiles": "photo-1511707171634-5f897ff02aa9",
    "Electronics": "photo-1517694712202-14dd9538aa97",
    "Fashion": "photo-1542291026-7eec264c27ff",
    "Home & Kitchen": "photo-1556909114-f6e7ad7d3136",
    "Books": "photo-1507842072343-583f20270319",
    "Sports & Fitness": "photo-1534438327276-14e5300c3a48",
    "Beauty & Personal Care": "photo-1556228578-8c89e6adf883",
    "Toys & Games": "photo-1611987867914-5c7947a0b1a3",
}

# Optional runtime overrides loaded from a fix file (name -> image URL or data URI).
FIX_IMAGE_MAP: dict[str, str] = {}


def normalize_mapping_key(value: Any) -> str:
    """Normalize product name keys for matching against fix mappings."""
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def load_fix_mappings(path: Optional[str] = None) -> None:
    """Load name->image mappings from a `fix.txt` file next to the repo root.

    File format (one mapping per line):
        Product Name:IMAGE_URL_OR_DATA_URI

    Loading is best-effort and silent if the file is not present.
    """
    global FIX_IMAGE_MAP
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fix.txt")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                name, url = line.split(":", 1)
                name = name.strip()
                url = url.strip()
                if not name or not url:
                    continue
                FIX_IMAGE_MAP[normalize_mapping_key(name)] = url
        app.logger.info("Loaded %d fix image mappings from %s", len(FIX_IMAGE_MAP), path)
    except Exception:
        app.logger.exception("Failed to read fix mappings from %s", path)


CATEGORY_META = {
    "Mobiles": {
        "icon": "bi-phone",
        "description": "Flagship launches, camera phones, and polished daily drivers grouped into clean product families.",
        "eyebrow": "Pocket tech",
        "featured_family_id": "mobile-apple-iphone-15-pro",
    },
    "Electronics": {
        "icon": "bi-cpu",
        "description": "Laptops, audio, tablets, and gaming gear with clearer browse flow and premium detail pages.",
        "eyebrow": "Power picks",
        "featured_family_id": "electronics-macbook-air-m3",
    },
    "Fashion": {
        "icon": "bi-handbag",
        "description": "Sneakers, outerwear, denim, and accessories with cleaner variant presentation and stronger imagery.",
        "eyebrow": "Wardrobe refresh",
        "featured_family_id": "fashion-nike-air-max",
    },
    "Home & Kitchen": {
        "icon": "bi-house-door",
        "description": "Countertop upgrades, coffee setups, and practical home picks that feel complete at a glance.",
        "eyebrow": "Home setup",
        "featured_family_id": "home-breville-espresso",
    },
    "Books": {
        "icon": "bi-book",
        "description": "Recognizable bestsellers across personal growth, finance, fiction, and memoir.",
        "eyebrow": "Shelf standouts",
        "featured_family_id": "book-atomic-habits",
    },
    "Sports & Fitness": {
        "icon": "bi-activity",
        "description": "Running, wearables, cycling, and yoga essentials arranged in a cleaner performance catalog.",
        "eyebrow": "Move better",
        "featured_family_id": "sport-peloton-bike",
    },
    "Beauty & Personal Care": {
        "icon": "bi-stars",
        "description": "Skincare, fragrance, and styling tools with variant-aware product pages and premium imagery.",
        "eyebrow": "Glow cabinet",
        "featured_family_id": "beauty-dyson-airwrap",
    },
    "Toys & Games": {
        "icon": "bi-controller",
        "description": "Build sets, party games, puzzles, and fun bundles that make the catalog feel broad and giftable.",
        "eyebrow": "Play mode",
        "featured_family_id": "toy-lego-creative-build",
    },
}

PAYMENT_METHODS = [
    {
        "id": "cod",
        "label": "Cash on Delivery",
        "caption": "Pay when your order reaches you.",
        "icon": "bi-cash-coin",
    },
    {
        "id": "upi",
        "label": "UPI / Wallet",
        "caption": "Fast checkout using your UPI ID or wallet handle.",
        "icon": "bi-phone",
    },
    {
        "id": "card",
        "label": "Credit / Debit Card",
        "caption": "Secure card checkout with credit or debit cards.",
        "icon": "bi-credit-card-2-front",
    },
    {
        "id": "netbanking",
        "label": "Net Banking",
        "caption": "Checkout directly through your bank account.",
        "icon": "bi-bank",
    },
]

SORT_OPTIONS = [
    {"id": "featured", "label": "Featured"},
    {"id": "newest", "label": "Newest"},
    {"id": "price_low", "label": "Price: Low to High"},
    {"id": "price_high", "label": "Price: High to Low"},
    {"id": "rating", "label": "Top Rated"},
]
VALID_SORTS = {option["id"] for option in SORT_OPTIONS}

cb_recommender: Any = None
collab_recommender: Any = None
products_df: Any = None
family_rows_by_id: dict[str, Any] = {}
family_cards_by_id: dict[str, dict[str, Any]] = {}
category_cards_cache: list[dict[str, Any]] = []
catalog_stats: dict[str, int] = {"product_count": 0, "family_count": 0, "category_count": 0}
catalog_ready: bool = False


@login_manager.user_loader # type: ignore
def load_user(user_id: Any) -> Any:
    return db.session.get(User, int(user_id)) # type: ignore


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def coerce_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_sort(value: Any) -> str:
    value_str = str(value or "featured").strip().lower()
    return value_str if value_str in VALID_SORTS else "featured"


def infer_brand(name: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9'&]+", " ", str(name)).strip()
    if not cleaned:
        return "ShadowMarket"
    tokens = cleaned.split()
    return " ".join(tokens[:2]) if tokens[0].lower() in {"the", "dr", "la"} and len(tokens) > 1 else tokens[0]


def format_money(value: Any) -> str:
    return f"${float(value):,.2f}"


def build_unsplash_url(photo_id: str, width: int, height: int, quality: int = 82) -> str:
    return f"https://images.unsplash.com/{photo_id}?auto=format&fit=crop&w={width}&h={height}&q={quality}"


def build_online_image_url(
    family_id: Any,
    name: Any,
    brand: Any,
    category: Any,
    subcategory: Any,
    width: int,
    height: int,
) -> str:
    category_key = str(category or "")
    photo_id = CATEGORY_FALLBACK_PHOTO_IDS.get(category_key)
    if photo_id:
        return build_unsplash_url(photo_id, width, height, quality=80 if width <= 720 else 82)

    # Safe fallback category for unknown rows.
    return build_unsplash_url(CATEGORY_FALLBACK_PHOTO_IDS["Electronics"], width, height, quality=80 if width <= 720 else 82)


def _as_row_dict(product_like: Any) -> dict[str, Any]:
    if isinstance(product_like, pd.Series):
        return product_like.to_dict() # type: ignore
    return dict(product_like) # type: ignore


def _build_family_seed(family_id: Any) -> int:
    return sum(ord(character) for character in str(family_id))


def _default_row_for_group(group: Any) -> Any:
    defaults: Any = group[group["is_default"]]
    return defaults.iloc[0] if not defaults.empty else group.iloc[0]


def enrich_product(product_like: Any, ensure_loaded: bool = True) -> dict[str, Any]:
    if ensure_loaded:
        ensure_catalog_loaded()

    data = _as_row_dict(product_like)
    product_id = int(data.get("product_id", 0) or 0)
    family_id: str = str(data.get("product_family_id") or f"family-{product_id}")
    family_group: Any = family_rows_by_id.get(family_id)

    category = str(data.get("category", "Uncategorized")).strip() or "Uncategorized"
    subcategory = str(data.get("subcategory", "")).strip()
    brand = str(data.get("brand", "")).strip() or infer_brand(data.get("name", ""))
    base_name = str(data.get("name", "Untitled Product")).strip() or "Untitled Product"
    variant_label = str(data.get("variant_label", "")).strip()
    variant_type = str(data.get("variant_type", "")).strip()
    price = round(float(data.get("price", 0.0) or 0.0), 2)
    thumb_image = data.get("thumb_image_url") or data.get("image_url") or PLACEHOLDER_IMAGE_PATH
    hero_image = data.get("hero_image_url") or thumb_image or PLACEHOLDER_IMAGE_PATH
    # If a fix mapping exists for this product name, override the images at render-time.
    full_name_candidate = f"{base_name} - {variant_label}" if variant_label else base_name
    mapped_url = None
    if FIX_IMAGE_MAP:
        mapped_url = FIX_IMAGE_MAP.get(normalize_mapping_key(full_name_candidate)) or FIX_IMAGE_MAP.get(normalize_mapping_key(base_name))
    if mapped_url:
        thumb_image = mapped_url
        hero_image = mapped_url
    thumb_fallback_image = build_online_image_url(
        family_id,
        base_name,
        brand,
        category,
        subcategory,
        width=720,
        height=720,
    )
    hero_fallback_image = build_online_image_url(
        family_id,
        base_name,
        brand,
        category,
        subcategory,
        width=1280,
        height=1280,
    )
    description = str(data.get("description", "")).strip()
    short_description = description if len(description) <= 108 else f"{description[:105].rstrip()}..."

    family_seed = _build_family_seed(family_id)
    latest_product_id: int = int(products_df["product_id"].max()) if products_df is not None and not products_df.empty else product_id # type: ignore

    if category == "Books":
        discount_percent = 10 + (family_seed % 3) * 4
    elif category in {"Beauty & Personal Care", "Toys & Games"}:
        discount_percent = 12 + (family_seed % 4) * 4
    else:
        discount_percent = 12 + (family_seed % 5) * 4

    original_price = round(price / (1 - discount_percent / 100), 2) if price else 0.0
    rating = round(min(4.9, 4.2 + (family_seed % 7) * 0.1), 1)
    review_count = 180 + (family_seed % 55) * 23
    badge = "New Drop" if product_id >= latest_product_id - 12 else "Hot Deal" if discount_percent >= 24 else "Best Seller"
    delivery_date = (datetime.now(timezone.utc) + timedelta(days=2 + (family_seed % 4))).strftime("%a, %d %b")
    variant_count: int = len(family_group) if family_group is not None else 1 # type: ignore
    full_name = f"{base_name} - {variant_label}" if variant_label else base_name

    return {
        "product_id": product_id,
        "primary_product_id": product_id,
        "family_id": family_id,
        "name": base_name,
        "full_name": full_name,
        "category": category,
        "category_slug": slugify(category),
        "subcategory": subcategory,
        "brand": brand,
        "description": description,
        "short_description": short_description,
        "variant_type": variant_type,
        "variant_value": str(data.get("variant_value", "")).strip(),
        "variant_label": variant_label,
        "variant_count": variant_count,
        "is_default": coerce_bool(data.get("is_default", False)),
        "price": price,
        "price_display": format_money(price),
        "original_price": original_price,
        "original_price_display": format_money(original_price),
        "discount_percent": discount_percent,
        "image": thumb_image,
        "hero_image": hero_image,
        "image_fallback": thumb_fallback_image,
        "hero_image_fallback": hero_fallback_image,
        "rating": rating,
        "review_count": review_count,
        "badge": badge,
        "stock_text": "Low stock" if (family_seed + product_id) % 6 == 0 else "Ready to ship",
        "delivery_text": f"Delivery by {delivery_date}",
        "has_price_range": False,
        "price_range_display": format_money(price),
        "price_caption": "",
        "variant_preview": [],
    }


def build_family_card(group: Any, ensure_loaded: bool = True) -> dict[str, Any]:
    if ensure_loaded:
        ensure_catalog_loaded()

    default_row = _default_row_for_group(group)
    base_product: dict[str, Any] = enrich_product(default_row, ensure_loaded=False)
    min_price = round(float(group["price"].min()), 2)
    max_price = round(float(group["price"].max()), 2)
    variant_labels = [
        str(value).strip()
        for value in group["variant_label"].tolist()
        if str(value).strip()
    ]
    preview: list[str] = []
    for label in variant_labels:
        if label not in preview:
            preview.append(label)
        if len(preview) >= 3:
            break

    base_discount = base_product["discount_percent"]
    original_price = round(min_price / (1 - base_discount / 100), 2) if min_price else 0.0
    newest_product_id = int(group["product_id"].max())
    variant_count: int = int(len(group)) # type: ignore

    base_product.update(
        {
            "price": min_price,
            "price_display": format_money(min_price),
            "original_price": original_price,
            "original_price_display": format_money(original_price),
            "has_price_range": min_price != max_price,
            "price_range_display": (
                f"{format_money(min_price)} - {format_money(max_price)}"
                if min_price != max_price
                else format_money(min_price)
            ),
            "price_caption": "From" if min_price != max_price else "",
            "variant_count": variant_count,
            "variant_preview": preview,
            "variant_summary": ", ".join(preview),
            "card_action_label": "View variants" if variant_count > 1 else "See details",
            "sort_price": min_price,
            "sort_newest": newest_product_id,
            "sort_rating": base_product["rating"],
            "sort_featured": round(
                base_product["rating"] * 10 + base_product["discount_percent"] + min(variant_count, 4),
                3,
            ),
        }
    )
    return base_product


def build_category_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    counts: Any = products_df["category"].value_counts() # type: ignore
    ordered_categories: list[str] = list(CATEGORY_META.keys()) + [
        category for category in counts.index.tolist() if category not in CATEGORY_META # type: ignore
    ]

    for category in ordered_categories:
        if category not in counts:
            continue

        meta: dict[str, Any] = CATEGORY_META.get(category, {})
        category_rows: Any = products_df[products_df["category"] == category] # type: ignore
        family_ids: list[str] = category_rows["product_family_id"].drop_duplicates().tolist() # type: ignore
        featured_family_id: str = str(meta.get("featured_family_id"))
        if featured_family_id not in family_cards_by_id and family_ids:
            featured_family_id = family_ids[0]

        family_card: dict[str, Any] = family_cards_by_id.get(featured_family_id, {})
        cards.append(
            {
                "name": category,
                "slug": slugify(category),
                "icon": meta.get("icon", "bi-grid"),
                "description": meta.get("description", "Fresh picks from the ShadowMarket shelves."),
                "eyebrow": meta.get("eyebrow", "Curated aisle"),
                "count": int(counts[category]), # type: ignore
                "family_count": len(family_ids),
                "image": family_card.get("hero_image") or family_card.get("image") or PLACEHOLDER_IMAGE_PATH,
                "image_fallback": family_card.get("hero_image_fallback") or family_card.get("image_fallback", ""),
                "starting_price_display": family_card.get("price_display", format_money(category_rows["price"].min())), # type: ignore
            }
        )

    return cards


def init_recommenders(force_reload: bool = False) -> None:
    global cb_recommender
    global collab_recommender
    global products_df
    global family_rows_by_id
    global family_cards_by_id
    global category_cards_cache
    global catalog_stats
    global catalog_ready

    if catalog_ready and not force_reload:
        return

    csv_path = os.path.join(os.path.dirname(__file__), "data", "products.csv")
    if not os.path.exists(csv_path):
        products_df = pd.DataFrame()
        family_rows_by_id = {}
        family_cards_by_id = {}
        category_cards_cache = []
        catalog_stats = {"product_count": 0, "family_count": 0, "category_count": 0}
        cb_recommender = None
        collab_recommender = None
        catalog_ready = True
        return

    products_df = pd.read_csv(csv_path).fillna("")
    defaults = {
        "product_family_id": "",
        "brand": "",
        "subcategory": "",
        "variant_type": "",
        "variant_value": "",
        "variant_label": "",
        "is_default": False,
        "thumb_image_url": "",
        "hero_image_url": "",
        "image_url": "",
    }
    for column, default in defaults.items():
        if column not in products_df.columns:
            products_df[column] = default

    products_df["product_id"] = pd.to_numeric(products_df["product_id"], errors="coerce").fillna(0).astype(int)
    products_df["price"] = pd.to_numeric(products_df["price"], errors="coerce").fillna(0.0)
    products_df["product_family_id"] = products_df["product_family_id"].astype(str).str.strip()
    missing_family_mask = products_df["product_family_id"] == ""
    if missing_family_mask.any():
        products_df.loc[missing_family_mask, "product_family_id"] = products_df.loc[missing_family_mask, "name"].apply(slugify)

    products_df["brand"] = products_df["brand"].astype(str).str.strip()
    brand_mask = products_df["brand"] == ""
    if brand_mask.any():
        products_df.loc[brand_mask, "brand"] = products_df.loc[brand_mask, "name"].apply(infer_brand)

    products_df["subcategory"] = products_df["subcategory"].astype(str).str.strip()
    products_df["variant_type"] = products_df["variant_type"].astype(str).str.strip()
    products_df["variant_value"] = products_df["variant_value"].astype(str).str.strip()
    products_df["variant_label"] = products_df["variant_label"].astype(str).str.strip()
    empty_variant_mask = products_df["variant_label"] == ""
    products_df.loc[empty_variant_mask, "variant_label"] = products_df.loc[empty_variant_mask, "variant_value"]
    products_df["is_default"] = products_df["is_default"].apply(coerce_bool)
    products_df["thumb_image_url"] = products_df["thumb_image_url"].astype(str).str.strip()
    products_df["hero_image_url"] = products_df["hero_image_url"].astype(str).str.strip()
    products_df["image_url"] = products_df["image_url"].astype(str).str.strip()
    thumb_mask = products_df["thumb_image_url"] == ""
    products_df.loc[thumb_mask, "thumb_image_url"] = products_df.loc[thumb_mask, "image_url"]
    hero_mask = products_df["hero_image_url"] == ""
    products_df.loc[hero_mask, "hero_image_url"] = products_df.loc[hero_mask, "thumb_image_url"]
    image_mask = products_df["image_url"] == ""
    products_df.loc[image_mask, "image_url"] = products_df.loc[image_mask, "thumb_image_url"]
    products_df = products_df.sort_values(["product_id"]).reset_index(drop=True)

    # Load any runtime name->image overrides before building family cards.
    load_fix_mappings()

    family_rows_by_id = {}
    family_cards_by_id = {}
    for family_id, group in products_df.groupby("product_family_id", sort=False):
        family_group = group.reset_index(drop=True)
        family_rows_by_id[family_id] = family_group # type: ignore
        family_cards_by_id[family_id] = build_family_card(family_group, ensure_loaded=False)

    category_cards_cache = build_category_cards()
    catalog_stats = {
        "product_count": int(len(products_df)),
        "family_count": len(family_rows_by_id),
        "category_count": int(products_df["category"].nunique()), # type: ignore
    }

    cb_recommender = ContentRecommender()
    cb_recommender.fit()

    interactions_path = os.path.join(os.path.dirname(__file__), "data", "interactions.csv")
    if os.path.exists(interactions_path):
        collab_recommender = CollabRecommender(n_components=10)
        # Lazy load collab model - don't train on startup to prevent timeout
    else:
        collab_recommender = None

    catalog_ready = True


def ensure_catalog_loaded() -> None:
    if not catalog_ready:
        init_recommenders()


def get_all_products() -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    return [enrich_product(row) for _, row in products_df.iterrows()] # type: ignore


def get_product_by_id(product_id: int) -> Optional[dict[str, Any]]:
    ensure_catalog_loaded()
    match: Any = products_df[products_df["product_id"] == int(product_id)] # type: ignore
    if match.empty: # type: ignore
        return None
    return enrich_product(match.iloc[0]) # type: ignore


def get_default_product_by_family_id(family_id: str) -> Optional[dict[str, Any]]:
    ensure_catalog_loaded()
    group: Any = family_rows_by_id.get(family_id)
    if group is None or group.empty: # type: ignore
        return None
    return enrich_product(_default_row_for_group(group))


def get_category_cards() -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    return [dict(card) for card in category_cards_cache]


def get_all_family_cards() -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    return sort_family_cards([dict(card) for card in family_cards_by_id.values()], "featured")


def resolve_category_name(category_slug: str) -> Optional[str]:
    for category in get_category_cards():
        if category["slug"] == category_slug:
            return category["name"]
    return None


def sort_family_cards(cards: list[dict[str, Any]], sort_value: Any) -> list[dict[str, Any]]:
    sort_value = normalize_sort(sort_value)

    if sort_value == "newest":
        return sorted(cards, key=lambda card: card.get("sort_newest", 0), reverse=True)
    if sort_value == "price_low":
        return sorted(cards, key=lambda card: (card.get("sort_price", 0), card.get("name", "")))
    if sort_value == "price_high":
        return sorted(cards, key=lambda card: (card.get("sort_price", 0), card.get("name", "")), reverse=True)
    if sort_value == "rating":
        return sorted(cards, key=lambda card: (card.get("sort_rating", 0), card.get("review_count", 0)), reverse=True)
    return sorted(
        cards,
        key=lambda card: (
            card.get("sort_featured", 0),
            card.get("sort_rating", 0),
            card.get("sort_newest", 0),
        ),
        reverse=True,
    )


def normalize_page(value: Any) -> int:
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def search_product_rows(query: str) -> Any:
    ensure_catalog_loaded()
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return products_df

    searchable_columns = [
        "name",
        "brand",
        "category",
        "subcategory",
        "variant_label",
        "description",
    ]

    haystack = (
        products_df[searchable_columns]
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    ) # type: ignore

    terms = [term for term in normalized_query.lower().split() if term]
    if not terms:
        return products_df

    match_mask: Any = haystack.str.contains(terms[0], na=False, regex=False)
    for term in terms[1:]:
        match_mask = match_mask & haystack.str.contains(term, na=False, regex=False)

    return products_df[match_mask] # type: ignore


def build_pagination(items: list[dict[str, Any]], page: int, per_page: int = RESULTS_PER_PAGE) -> dict[str, Any]:
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page) if total_items else 1
    current_page = min(max(page, 1), total_pages)
    start_index = (current_page - 1) * per_page
    end_index = start_index + per_page
    page_items = items[start_index:end_index]

    def build_page_url(target_page: int) -> str:
        params = request.args.to_dict()
        if target_page <= 1:
            params.pop("page", None)
        else:
            params["page"] = str(target_page)
        return url_for(request.endpoint or "search", **(request.view_args or {}), **params)  # type: ignore

    page_numbers = list(range(max(1, current_page - 2), min(total_pages, current_page + 2) + 1))

    return {
        "items": page_items,
        "page": current_page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "start_item": start_index + 1 if total_items else 0,
        "end_item": min(end_index, total_items),
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "prev_url": build_page_url(current_page - 1) if current_page > 1 else None,
        "next_url": build_page_url(current_page + 1) if current_page < total_pages else None,
        "pages": [
            {
                "number": page_number,
                "url": build_page_url(page_number),
                "is_current": page_number == current_page,
            }
            for page_number in page_numbers
        ],
    }


def get_recently_viewed_product_ids(exclude_product_id: Any = None) -> list[int]:
    recent_items = session.get("recently_viewed", [])
    product_ids: list[int] = []

    for value in recent_items:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if exclude_product_id is not None and product_id == int(exclude_product_id):
            continue
        if product_id not in product_ids:
            product_ids.append(product_id)

    return product_ids[:RECENTLY_VIEWED_LIMIT]


def record_recently_viewed(product_id: int) -> None:
    recent_items = get_recently_viewed_product_ids(exclude_product_id=product_id)
    session["recently_viewed"] = [int(product_id)] + recent_items[: RECENTLY_VIEWED_LIMIT - 1]
    session.modified = True


def fill_family_card_gaps(
    cards: list[dict[str, Any]],
    limit: int,
    exclude_family_ids: Optional[list[str]] = None,
    preferred_categories: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    filled = [dict(card) for card in cards[:limit]]
    seen_family_ids = {card["family_id"] for card in filled}

    for family_id in exclude_family_ids or []:
        if family_id:
            seen_family_ids.add(str(family_id))

    candidate_groups: list[list[dict[str, Any]]] = []
    for category_name in preferred_categories or []:
        if category_name:
            candidate_groups.append(get_family_cards_for_category(category_name, sort_value="featured"))
    candidate_groups.append(get_all_family_cards())

    for candidate_group in candidate_groups:
        for card in candidate_group:
            family_id = str(card["family_id"])
            if family_id in seen_family_ids:
                continue
            filled.append(dict(card))
            seen_family_ids.add(family_id)
            if len(filled) >= limit:
                return filled

    return filled


def get_family_cards_from_rows(rows: Any, sort_value: Any = "featured", limit: Optional[int] = None, exclude_family_id: Any = None) -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    if rows is None or rows.empty: # type: ignore
        return []

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, row in rows.sort_values(["product_id"], ascending=False).iterrows(): # type: ignore
        family_id = str(row["product_family_id"])
        if family_id in seen or family_id == exclude_family_id or family_id not in family_cards_by_id:
            continue
        cards.append(dict(family_cards_by_id[family_id]))
        seen.add(family_id)

    cards = sort_family_cards(cards, sort_value)
    return cards[:limit] if limit is not None else cards


def get_family_cards_for_category(category_name: str, sort_value: Any = "featured") -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    matched_rows: Any = products_df[products_df["category"].str.lower() == category_name.lower()] # type: ignore
    return get_family_cards_from_rows(matched_rows, sort_value=sort_value)


def dedupe_family_cards_from_products(products: list[Any], limit: Optional[int] = None, exclude_family_id: Any = None) -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    for product in products:
        enriched = enrich_product(product)
        family_id = enriched["family_id"]
        if family_id in seen or family_id == exclude_family_id or family_id not in family_cards_by_id:
            continue
        cards.append(dict(family_cards_by_id[family_id]))
        seen.add(family_id)
        if limit is not None and len(cards) >= limit:
            break

    return cards


def build_variant_options(family_id: str, active_product_id: int) -> list[dict[str, Any]]:
    ensure_catalog_loaded()
    group: Any = family_rows_by_id.get(family_id)
    if group is None or len(group) <= 1:
        return []

    options: list[dict[str, Any]] = []
    for _, row in group.iterrows():
        product = enrich_product(row)
        options.append(
            {
                "product_id": product["product_id"],
                "label": product["variant_label"] or "Standard",
                "price_display": product["price_display"],
                "is_active": product["product_id"] == active_product_id,
                "is_default": product["is_default"],
            }
        )
    return options


def get_search_terms() -> list[str]:
    ensure_catalog_loaded()
    family_terms: list[str] = [card["name"] for card in get_all_family_cards()[:18]]
    brand_terms: list[str] = products_df["brand"].drop_duplicates().head(18).tolist() # type: ignore
    subcategory_terms: list[str] = products_df["subcategory"].drop_duplicates().head(18).tolist() # type: ignore
    category_terms: list[str] = [card["name"] for card in get_category_cards()]

    ordered_terms: list[str] = []
    seen: set[str] = set()
    for term in family_terms + brand_terms + subcategory_terms + category_terms:
        if not term or term in seen:
            continue
        seen.add(term)
        ordered_terms.append(term)
    return ordered_terms[:36]


def get_cart_map() -> dict[str, Any]:
    return session.get("cart", {})


def save_cart_map(cart_map: dict[str, Any]) -> None:
    session["cart"] = cart_map
    session.modified = True


def add_to_cart_state(product_id: int, quantity: int = 1, replace: bool = False) -> None:
    cart_map = get_cart_map()
    product_key = str(product_id)
    current_quantity = int(cart_map.get(product_key, 0))
    cart_map[product_key] = max(1, quantity) if replace else current_quantity + max(1, quantity)
    save_cart_map(cart_map)


def remove_from_cart_state(product_id: int) -> None:
    cart_map = get_cart_map()
    cart_map.pop(str(product_id), None)
    save_cart_map(cart_map)


def get_cart_items() -> list[dict[str, Any]]:
    items = []
    cart_map = get_cart_map()
    dirty = False

    for product_key, quantity in cart_map.items():
        product = get_product_by_id(int(product_key))
        if product is None:
            dirty = True
            continue
        item = dict(product)
        item["quantity"] = int(quantity)
        item["subtotal"] = round(item["price"] * item["quantity"], 2)
        item["subtotal_display"] = format_money(item["subtotal"])
        items.append(item)

    if dirty:
        cleaned_cart: dict[str, Any] = {str(item["product_id"]): item["quantity"] for item in items}
        save_cart_map(cleaned_cart)

    return items


def get_cart_summary(cart_items: list[dict[str, Any]]) -> dict[str, Any]:
    subtotal = round(sum(item["subtotal"] for item in cart_items), 2)
    shipping = 0.0 if subtotal == 0 or subtotal >= FREE_SHIPPING_THRESHOLD else STANDARD_SHIPPING_FEE
    tax = round(subtotal * ESTIMATED_TAX_RATE, 2)
    total = round(subtotal + shipping + tax, 2)
    savings = round(
        sum((item["original_price"] - item["price"]) * item["quantity"] for item in cart_items),
        2,
    )

    return {
        "subtotal": subtotal,
        "subtotal_display": format_money(subtotal),
        "shipping": shipping,
        "shipping_display": "Free" if shipping == 0 else format_money(shipping),
        "tax": tax,
        "tax_display": format_money(tax),
        "total": total,
        "total_display": format_money(total),
        "savings": savings,
        "savings_display": format_money(savings),
        "free_shipping_gap": max(FREE_SHIPPING_THRESHOLD - subtotal, 0.0),
        "free_shipping_gap_display": format_money(max(FREE_SHIPPING_THRESHOLD - subtotal, 0.0)),
        "item_count": sum(item["quantity"] for item in cart_items),
    }


def build_order_payload(cart_items: list[dict[str, Any]], summary: dict[str, Any], form_data: dict[str, Any]) -> dict[str, Any]:
    payment_method = next(
        (method for method in PAYMENT_METHODS if method["id"] == form_data["payment_method"]),
        PAYMENT_METHODS[0],
    )
    eta = (datetime.now(timezone.utc) + timedelta(days=4)).strftime("%A, %d %b")
    payment_status = "Pay on delivery" if payment_method["id"] == "cod" else "Demo payment confirmed"

    return {
        "id": f"SM-{uuid4().hex[:8].upper()}",
        "placed_at": datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p"),
        "eta": eta,
        "customer": {
            "full_name": form_data["full_name"],
            "email": form_data["email"],
            "phone": form_data["phone"],
            "address": form_data["address"],
            "city": form_data["city"],
            "postal_code": form_data["postal_code"],
        },
        "payment_method": payment_method["label"],
        "payment_status": payment_status,
        "payment_method_id": payment_method["id"],
        "items": cart_items,
        "summary": summary,
    }


def save_order(order_payload: dict[str, Any]) -> None:
    orders = session.get("orders", [])
    orders.insert(0, order_payload)
    session["orders"] = orders[:5]
    session["last_order"] = order_payload
    session.modified = True


def record_order_interactions(cart_items: list[dict[str, Any]]) -> None:
    if not current_user.is_authenticated: # type: ignore
        return

    for item in cart_items:
        interaction = Interaction.query.filter_by(
            user_id=current_user.id, product_id=item["product_id"] # type: ignore
        ).first() # type: ignore
        if interaction:
            interaction.quantity += item["quantity"] # type: ignore
        else:
            db.session.add(
                Interaction(
                    user_id=current_user.id, # type: ignore
                    product_id=item["product_id"],  # type: ignore
                    quantity=item["quantity"],  # type: ignore
                )
            )
    db.session.commit() # type: ignore


@app.context_processor
def inject_global_context() -> dict[str, Any]:
    ensure_catalog_loaded()
    categories = get_category_cards()
    cart_items = get_cart_items()
    cart_summary = get_cart_summary(cart_items)

    return {
        "site_name": SITE_NAME,
        "categories": categories,
        "cart_count": cart_summary["item_count"],
        "cart_total": cart_summary["total_display"],
        "footer_year": datetime.now(timezone.utc).year,
        "search_terms": get_search_terms(),
        "placeholder_image": url_for("static", filename="images/product-placeholder.svg"),
        "catalog_stats": catalog_stats,
        "sort_options": SORT_OPTIONS,
    }


@app.route("/")
def index():
    ensure_catalog_loaded()
    hero_product = get_default_product_by_family_id(HOME_HERO_FAMILY_ID) or (get_all_products()[0] if not products_df.empty else None) # type: ignore
    featured_categories = get_category_cards()
    family_catalog = get_all_family_cards()

    recommended_source: list[Any] = []
    preferred_categories: list[str] = []
    hero_family_id = hero_product["family_id"] if hero_product else None
    recently_viewed_ids = get_recently_viewed_product_ids(exclude_product_id=hero_product["product_id"] if hero_product else None)

    if current_user.is_authenticated and current_user.interactions: # type: ignore
        interacted_ids = [interaction.product_id for interaction in current_user.interactions] # type: ignore
        preferred_categories.extend(
            products_df[products_df["product_id"].isin(interacted_ids)]["category"].drop_duplicates().tolist() # type: ignore
        )

    if current_user.is_authenticated and collab_recommender is not None: # type: ignore
        # Lazy load collab model on first request
        if collab_recommender.model is None:
            collab_recommender.fit()
        if collab_recommender.model is not None:
            recommended_source.extend(
                collab_recommender.recommend_for_user(current_user.id, top_n=RECOMMENDATION_POOL_SIZE) # type: ignore
            )
        if current_user.interactions and cb_recommender is not None: # type: ignore
            user_interactions = pd.DataFrame(
                [
                    {
                        "user_id": current_user.id, # type: ignore
                        "product_id": interaction.product_id, # type: ignore
                        "quantity": interaction.quantity, # type: ignore
                    }
                    for interaction in current_user.interactions # type: ignore
                ]
            )
            recommended_source.extend(
                cb_recommender.recommend_for_user(user_interactions, current_user.id, top_n=RECOMMENDATION_POOL_SIZE) # type: ignore
            )

    if cb_recommender is not None:
        for product_id in recently_viewed_ids[:3]:
            recent_product = get_product_by_id(product_id)
            if recent_product is None:
                continue
            if recent_product["category"] not in preferred_categories:
                preferred_categories.append(recent_product["category"])
            recommended_source.extend(
                cb_recommender.recommend_similar(
                    recent_product["product_id"],
                    top_n=10,
                    exclude_family_ids=[hero_family_id] if hero_family_id else None,
                )
            )

    if not recommended_source and hero_product is not None and cb_recommender is not None:
        recommended_source = cb_recommender.recommend_similar(
            hero_product["product_id"],
            top_n=RECOMMENDATION_POOL_SIZE,
            exclude_family_ids=[hero_family_id] if hero_family_id else None,
        )

    recommended_for_you = dedupe_family_cards_from_products(
        recommended_source,
        limit=HOME_RECOMMENDATION_LIMIT,
        exclude_family_id=hero_family_id,
    )
    recommended_for_you = fill_family_card_gaps(
        recommended_for_you,
        HOME_RECOMMENDATION_LIMIT,
        exclude_family_ids=[hero_family_id] if hero_family_id else None,
        preferred_categories=preferred_categories,
    )
    trending_products = sort_family_cards(list(family_catalog), "rating")[:4]
    top_deals = sorted(
        list(family_catalog),
        key=lambda product: (product["discount_percent"], -product["sort_price"]),
        reverse=True,
    )[:4]
    new_arrivals = sort_family_cards(list(family_catalog), "newest")[:4]
    spotlight_features = [
        {
            "icon": "bi-images",
            "title": "Fresh arrivals daily",
            "text": "Discover new drops across mobiles, fashion, beauty, books, and home essentials in one place.",
        },
        {
            "icon": "bi-layout-text-window-reverse",
            "title": "More choice per item",
            "text": "Every product family includes practical options for storage, size, color, and premium bundles.",
        },
        {
            "icon": "bi-lightning-charge",
            "title": "Checkout made simple",
            "text": "Add to cart, compare options, and place your order with card, UPI, net banking, or cash on delivery.",
        },
    ]

    return render_template(
        "index.html",
        hero_product=hero_product,
        featured_categories=featured_categories[:8],
        recommended_for_you=recommended_for_you,
        trending_products=trending_products,
        top_deals=top_deals,
        new_arrivals=new_arrivals,
        spotlight_features=spotlight_features,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated: # type: ignore
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user: Any = User.query.filter_by(username=form.username.data).first() # type: ignore
        if user and user.check_password(form.password.data):
            login_user(user) # type: ignore
            flash("Welcome back to ShadowMarket.", "success")
            return redirect(url_for("index"))
        flash("Invalid username or password.", "warning")

    return render_template("login.html", form=form)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated: # type: ignore
        return redirect(url_for("index"))

    form = SignupForm()
    if form.validate_on_submit():
        existing_username: Any = User.query.filter_by(username=form.username.data).first() # type: ignore
        if existing_username:
            flash("That username is already taken.", "warning")
            return redirect(url_for("signup"))

        existing_email: Any = User.query.filter_by(email=form.email.data).first() # type: ignore
        if existing_email:
            flash("That email address is already registered.", "warning")
            return redirect(url_for("signup"))

        user = User(username=form.username.data, email=form.email.data)  # type: ignore
        user.set_password(form.password.data or "")  # type: ignore
        db.session.add(user) # type: ignore
        db.session.commit() # type: ignore
        flash("Account created successfully. Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html", form=form)


@app.route("/logout")
@login_required # type: ignore
def logout(): # type: ignore
    logout_user() # type: ignore
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/about")
def about():
    return render_template("about.html", site_name=SITE_NAME)


@app.route("/search", methods=["GET", "POST"])
def search():
    ensure_catalog_loaded()
    query = (request.values.get("query") or "").strip()
    selected_sort = normalize_sort(request.values.get("sort"))
    current_page = normalize_page(request.values.get("page"))
    matched_rows = search_product_rows(query)
    family_cards = get_family_cards_from_rows(matched_rows, sort_value=selected_sort)
    pagination = build_pagination(family_cards, current_page)

    return render_template(
        "results.html",
        recommendations=pagination["items"],
        query=query,
        selected_sort=selected_sort,
        result_count=pagination["total_items"],
        pagination=pagination,
        view_title=f"Search results for '{query}'" if query else "Browse the full catalog",
    )


@app.route("/category/<category_slug>")
def category_products(category_slug: str):
    ensure_catalog_loaded()
    category_name = resolve_category_name(category_slug)
    if not category_name:
        flash("That category was not found.", "warning")
        return redirect(url_for("index"))

    selected_sort = normalize_sort(request.args.get("sort"))
    current_page = normalize_page(request.args.get("page"))
    family_cards = get_family_cards_for_category(category_name, sort_value=selected_sort)
    pagination = build_pagination(family_cards, current_page)

    return render_template(
        "results.html",
        recommendations=pagination["items"],
        category=category_name,
        selected_sort=selected_sort,
        result_count=pagination["total_items"],
        pagination=pagination,
        view_title=f"{category_name} storefront",
    )


@app.route("/product/<int:product_id>")
def product(product_id):
    ensure_catalog_loaded()
    product_data = get_product_by_id(product_id)
    if product_data is None:
        flash("Product not found.", "warning")
        return redirect(url_for("index"))

    record_recently_viewed(product_id)
    variant_options = build_variant_options(product_data["family_id"], product_id)
    similar_products = []
    if cb_recommender is not None:
        similar_products = dedupe_family_cards_from_products(
            cb_recommender.recommend_similar(
                product_id,
                top_n=RECOMMENDATION_POOL_SIZE,
                exclude_family_ids=[product_data["family_id"]],
            ),
            limit=4,
            exclude_family_id=product_data["family_id"],
        )
    similar_products = fill_family_card_gaps(
        similar_products,
        4,
        exclude_family_ids=[product_data["family_id"]],
        preferred_categories=[product_data["category"]],
    )

    return render_template(
        "product.html",
        product=product_data,
        variant_options=variant_options,
        similar_products=similar_products,
    )


@app.route("/cart")
def cart():
    cart_items = get_cart_items()
    cart_summary = get_cart_summary(cart_items)
    cart_family_ids = {item["family_id"] for item in cart_items}
    recommended_products = [
        product for product in get_all_family_cards() if product["family_id"] not in cart_family_ids
    ][:4]

    return render_template(
        "cart.html",
        cart_items=cart_items,
        cart_summary=cart_summary,
        recommended_products=recommended_products,
    )


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def add_to_cart(product_id: int):
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "warning")
        return redirect(url_for("index"))

    quantity = max(1, min(int(request.form.get("quantity", 1) or 1), 6))
    add_to_cart_state(product_id, quantity=quantity)
    flash(f"{product['full_name']} was added to your cart.", "success")

    next_url = request.form.get("next") or request.referrer or url_for("cart")
    return redirect(next_url)


@app.route("/buy-now/<int:product_id>", methods=["POST"])
def buy_now(product_id: int):
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "warning")
        return redirect(url_for("index"))

    add_to_cart_state(product_id, quantity=1)
    return redirect(url_for("checkout"))


@app.route("/cart/update/<int:product_id>", methods=["POST"])
def update_cart_item(product_id: int):
    product = get_product_by_id(product_id)
    if product is None:
        flash("Product not found.", "warning")
        return redirect(url_for("cart"))

    quantity = max(1, min(int(request.form.get("quantity", 1) or 1), 6))
    add_to_cart_state(product_id, quantity=quantity, replace=True)
    flash(f"Updated quantity for {product['full_name']}.", "success")
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:product_id>", methods=["POST"])
def remove_from_cart(product_id: int):
    product = get_product_by_id(product_id)
    remove_from_cart_state(product_id)

    if product is not None:
        flash(f"Removed {product['full_name']} from your cart.", "info")
    else:
        flash("Item removed from your cart.", "info")

    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_items = get_cart_items()
    if not cart_items:
        flash("Your cart is empty. Add a few products before checkout.", "warning")
        return redirect(url_for("index"))

    cart_summary = get_cart_summary(cart_items)
    form_data: dict[str, Any] = {
        "full_name": getattr(current_user, "username", "") if current_user.is_authenticated else "",  # type: ignore
        "email": getattr(current_user, "email", "") if current_user.is_authenticated else "",  # type: ignore
        "phone": "",
        "address": "",
        "city": "",
        "postal_code": "",
        "payment_method": "cod",
        "upi_id": "",
        "card_name": "",
        "card_number": "",
        "bank_name": "",
    }

    if request.method == "POST":
        for key in form_data:
            form_data[key] = (request.form.get(key) or "").strip()

        required_fields = ["full_name", "email", "phone", "address", "city", "postal_code", "payment_method"]
        missing_fields = [field for field in required_fields if not form_data[field]]
        if missing_fields:
            flash("Please complete all required checkout fields.", "warning")
            return render_template(
                "checkout.html",
                cart_items=cart_items,
                cart_summary=cart_summary,
                payment_methods=PAYMENT_METHODS,
                form_data=form_data,
            )

        if form_data["payment_method"] == "upi" and not form_data["upi_id"]:
            flash("Please enter a valid UPI or wallet handle.", "warning")
        elif form_data["payment_method"] == "card" and (
            not form_data["card_name"] or not form_data["card_number"]
        ):
            flash("Please enter the card holder name and card number.", "warning")
        elif form_data["payment_method"] == "netbanking" and not form_data["bank_name"]:
            flash("Please choose a bank for net banking.", "warning")
        else:
            order_payload = build_order_payload(cart_items, cart_summary, form_data)
            record_order_interactions(cart_items)
            save_order(order_payload)
            save_cart_map({})
            flash("Order placed successfully.", "success")
            return redirect(url_for("order_success", order_id=order_payload["id"]))

    return render_template(
        "checkout.html",
        cart_items=cart_items,
        cart_summary=cart_summary,
        payment_methods=PAYMENT_METHODS,
        form_data=form_data,
    )


@app.route("/order-success/<order_id>")
def order_success(order_id: str):
    last_order = session.get("last_order")
    if last_order and last_order.get("id") == order_id:
        order_payload = last_order
    else:
        order_payload = next(
            (order for order in session.get("orders", []) if order.get("id") == order_id),
            None,
        )

    if order_payload is None:
        flash("We could not find that order confirmation.", "warning")
        return redirect(url_for("index"))

    recommended_products = get_all_family_cards()[:4]
    return render_template(
        "order_success.html",
        order=order_payload,
        recommended_products=recommended_products,
    )


@app.route("/interact", methods=["POST"])
@login_required # type: ignore
def interact(): # type: ignore
    data: dict[str, Any] = request.get_json() or {}
    product_id: Any = data.get("product_id")

    if not product_id:
        return jsonify({"message": "Product ID required"}), 400

    interaction: Any = Interaction.query.filter_by(user_id=current_user.id, product_id=product_id).first() # type: ignore
    if interaction:
        interaction.quantity += 1 # type: ignore
    else:
        interaction = Interaction(user_id=current_user.id, product_id=product_id) # type: ignore
        db.session.add(interaction) # type: ignore

    db.session.commit() # type: ignore
    return jsonify({"message": "Saved to your ShadowMarket likes."})


if __name__ == "__main__":
    from data.generate_dataset import create_interactions, create_products

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    products_file = os.path.join(data_dir, "products.csv")
    interactions_file = os.path.join(data_dir, "interactions.csv")

    needs_catalog_refresh = True
    if os.path.exists(products_file):
        try:
            preview = pd.read_csv(products_file)
            needs_catalog_refresh = (
                len(preview) < 220
                or
                "product_family_id" not in preview.columns
                or "thumb_image_url" not in preview.columns
                or "hero_image_url" not in preview.columns
            )
        except Exception:
            needs_catalog_refresh = True

    if needs_catalog_refresh or not os.path.exists(products_file):
        create_products()
    if needs_catalog_refresh or not os.path.exists(interactions_file):
        create_interactions()

    with app.app_context():
        db.create_all() # type: ignore
        init_recommenders(force_reload=True)

    app.run(debug=True)
