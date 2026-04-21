import os
import re
import smtplib
import threading
import time
from functools import wraps
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import uuid4
from typing import Any, Optional, cast

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from admin_forms import AdminDiscountForm, AdminLoginForm, AdminOrderStatusForm, AdminProductForm, AdminTicketUpdateForm
from forms import LoginForm, SignupForm
from models import AdminAuditLog, AdminProduct, DiscountRule, Interaction, Order, SupportTicket, User, db
from recommenders.collab import CollabRecommender
from recommenders.content_based import ContentRecommender

try:
    import stripe # type: ignore
except Exception:
    stripe = None

try:
    import resend # type: ignore
except Exception:
    resend = None

try:
    import pyotp # type: ignore
except Exception:
    pyotp = None

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "your-secret-key-here-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///site.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app) # type: ignore
login_manager = LoginManager(app) # type: ignore
login_manager.login_view = "login" # type: ignore

_db_initialized = False
_mail_config_logged = False
_admin_config_logged = False
_admin_failed_attempts: dict[str, list[float]] = {}

@app.before_request
def initialize_database():
    global _db_initialized
    if not _db_initialized:
        log_mail_configuration_once()
        log_admin_configuration_once()
        db.create_all() # type: ignore
        _db_initialized = True

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
_discount_overrides_cache: dict[str, int] = {}
_discount_overrides_loaded_at: float = 0.0


def _mask_secret(value: str) -> str:
    raw = str(value or "")
    if len(raw) <= 4:
        return "****"
    return f"****{raw[-4:]}"


def log_mail_configuration_once() -> None:
    global _mail_config_logged
    if _mail_config_logged:
        return
    _mail_config_logged = True

    api_key = str(os.environ.get("RESEND_API_KEY", "") or "").strip()
    smtp_server = str(os.environ.get("MAIL_SERVER", "") or "").strip()
    smtp_username = str(os.environ.get("MAIL_USERNAME", "") or "").strip()
    from_name = str(os.environ.get("MAIL_FROM_NAME", SITE_NAME) or SITE_NAME).strip() or SITE_NAME
    from_address = str(os.environ.get("MAIL_FROM_ADDRESS", "onboarding@resend.dev") or "").strip()

    if api_key and resend is not None:
        app.logger.info(
            "Email enabled: Resend configured (from=%s <%s>, key=%s).",
            from_name,
            from_address or "onboarding@resend.dev",
            _mask_secret(api_key),
        )
        return

    if api_key and resend is None:
        app.logger.warning("Email disabled: resend package is not available.")
        return

    if smtp_server and smtp_username:
        app.logger.info(
            "Email enabled: SMTP configured (server=%s, user=%s, from=%s <%s>).",
            smtp_server,
            _mask_secret(smtp_username),
            from_name,
            from_address or "onboarding@resend.dev",
        )
        return

    app.logger.warning(
        "Email disabled: set RESEND_API_KEY (recommended) or SMTP (MAIL_SERVER/MAIL_USERNAME/MAIL_PASSWORD)."
    )


def get_admin_config() -> dict[str, Any]:
    return {
        "enabled": coerce_bool(os.environ.get("ADMIN_ENABLED", "true")),
        "email": str(os.environ.get("ADMIN_EMAIL", "") or "").strip().lower(),
        "password_hash": str(os.environ.get("ADMIN_PASSWORD_HASH", "") or "").strip(),
        "password_plain": str(os.environ.get("ADMIN_PASSWORD", "") or ""),
        "totp_secret": str(os.environ.get("ADMIN_TOTP_SECRET", "") or "").strip().replace(" ", ""),
        "issuer": str(os.environ.get("ADMIN_2FA_ISSUER", f"{SITE_NAME} Admin") or f"{SITE_NAME} Admin").strip(),
        "require_2fa": coerce_bool(os.environ.get("ADMIN_REQUIRE_2FA", "true")),
        "max_attempts": int(str(os.environ.get("ADMIN_MAX_ATTEMPTS", "10") or "10")),
        "window_seconds": int(str(os.environ.get("ADMIN_ATTEMPT_WINDOW_SECONDS", "600") or "600")),
    }


def log_admin_configuration_once() -> None:
    global _admin_config_logged
    if _admin_config_logged:
        return
    _admin_config_logged = True

    cfg = get_admin_config()
    if not cfg["enabled"]:
        app.logger.info("Admin panel disabled (ADMIN_ENABLED=false).")
        return

    email = str(cfg.get("email") or "")
    has_password = bool(cfg.get("password_hash") or cfg.get("password_plain"))
    if not email or not has_password:
        app.logger.warning("Admin panel not configured: set ADMIN_EMAIL and ADMIN_PASSWORD_HASH (or ADMIN_PASSWORD).")
        return

    require_2fa = bool(cfg.get("require_2fa"))
    totp_secret = str(cfg.get("totp_secret") or "")
    if require_2fa and (pyotp is None or not totp_secret):
        app.logger.warning("Admin panel requires 2FA but is not ready: set ADMIN_TOTP_SECRET and install pyotp.")
        return

    app.logger.info(
        "Admin panel enabled: email=%s, 2fa=%s.",
        email,
        "required" if require_2fa else "optional",
    )


def _admin_client_ip() -> str:
    forwarded_for = str(request.headers.get("X-Forwarded-For", "") or "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return str(request.remote_addr or "")


def _admin_prune_attempts(ip: str, window_seconds: int) -> list[float]:
    now = time.time()
    attempts = _admin_failed_attempts.get(ip, [])
    attempts = [timestamp for timestamp in attempts if now - timestamp <= window_seconds]
    _admin_failed_attempts[ip] = attempts
    return attempts


def _admin_is_rate_limited(ip: str, max_attempts: int, window_seconds: int) -> bool:
    attempts = _admin_prune_attempts(ip, window_seconds)
    return len(attempts) >= max_attempts


def _admin_record_failure(ip: str) -> None:
    _admin_failed_attempts.setdefault(ip, []).append(time.time())


def _admin_totp_valid(secret: str, code: str) -> bool:
    if not secret or not code or pyotp is None:
        return False
    normalized = re.sub(r"\\s+", "", str(code))
    if not normalized.isdigit():
        return False
    totp = pyotp.TOTP(secret) # type: ignore[union-attr]
    return bool(totp.verify(normalized, valid_window=1))


def admin_is_authenticated() -> bool:
    cfg = get_admin_config()
    if not cfg.get("enabled", True):
        return False
    expected_email = str(cfg.get("email") or "")
    if not expected_email:
        return False
    return bool(session.get("admin_authed") is True and session.get("admin_email") == expected_email)


def admin_required(view_fn):  # type: ignore
    @wraps(view_fn)
    def wrapper(*args, **kwargs):  # type: ignore
        cfg = get_admin_config()
        if not cfg.get("enabled", True):
            flash("Admin panel is disabled.", "warning")
            return redirect(url_for("index"))
        if not admin_is_authenticated():
            flash("Please sign in to access the admin panel.", "warning")
            return redirect(url_for("admin_login", next=request.path))
        return view_fn(*args, **kwargs)

    return wrapper


def admin_audit(action: str, target_type: str = "", target_id: str = "", detail: str = "") -> None:
    cfg = get_admin_config()
    if not cfg.get("enabled", True):
        return
    admin_email = str(session.get("admin_email") or "")
    if not admin_email:
        return

    try:
        entry = AdminAuditLog(
            admin_email=admin_email,  # type: ignore
            action=str(action or "")[:180],  # type: ignore
            target_type=str(target_type or "")[:80],  # type: ignore
            target_id=str(target_id or "")[:120],  # type: ignore
            detail=str(detail or "")[:4000],  # type: ignore
            ip_address=_admin_client_ip()[:80],  # type: ignore
        )
        db.session.add(entry) # type: ignore
        db.session.commit() # type: ignore
    except Exception:
        app.logger.exception("Failed to write admin audit log entry.")


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
        "label": "Card (Stripe)",
        "caption": "Pay securely with Stripe checkout.",
        "icon": "bi-credit-card-2-front",
    },
    {
        "id": "netbanking",
        "label": "Net Banking",
        "caption": "Checkout directly through your bank account.",
        "icon": "bi-bank",
    },
]

ORDER_STATUS_FLOW = [
    {
        "id": "pending_payment",
        "label": "Payment Pending",
        "description": "Waiting for payment confirmation.",
        "icon": "bi-hourglass-split",
    },
    {
        "id": "confirmed",
        "label": "Order Confirmed",
        "description": "Your order was received successfully.",
        "icon": "bi-check2-circle",
    },
    {
        "id": "processing",
        "label": "Processing",
        "description": "We are packing your items.",
        "icon": "bi-box-seam",
    },
    {
        "id": "shipped",
        "label": "Shipped",
        "description": "Your package is on the move.",
        "icon": "bi-truck",
    },
    {
        "id": "out_for_delivery",
        "label": "Out for Delivery",
        "description": "Your package is near your address.",
        "icon": "bi-bicycle",
    },
    {
        "id": "delivered",
        "label": "Delivered",
        "description": "Delivered successfully.",
        "icon": "bi-house-door",
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


def get_stripe_config() -> dict[str, Any]:
    return {
        "secret_key": str(os.environ.get("STRIPE_SECRET_KEY", "")).strip(),
        "publishable_key": str(os.environ.get("STRIPE_PUBLISHABLE_KEY", "")).strip(),
        "currency": str(os.environ.get("STRIPE_CURRENCY", "usd")).strip().lower() or "usd",
    }


def is_stripe_ready() -> bool:
    stripe_config = get_stripe_config()
    return stripe is not None and bool(stripe_config["secret_key"])


def build_tracking_timeline(current_status: str, placed_at_display: str, eta: str) -> list[dict[str, Any]]:
    status_ids = [step["id"] for step in ORDER_STATUS_FLOW]
    safe_status = current_status if current_status in status_ids else "processing"
    active_index = status_ids.index(safe_status)
    timeline: list[dict[str, Any]] = []

    for index, step in enumerate(ORDER_STATUS_FLOW):
        if index < active_index:
            state = "completed"
        elif index == active_index:
            state = "active"
        else:
            state = "upcoming"

        detail = step["description"]
        if step["id"] == "confirmed":
            detail = placed_at_display
        elif step["id"] in {"shipped", "out_for_delivery", "delivered"}:
            detail = f"Estimated by {eta}"

        timeline.append(
            {
                "id": step["id"],
                "title": step["label"],
                "detail": detail,
                "icon": step["icon"],
                "state": state,
            }
        )

    return timeline


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


def invalidate_discount_overrides() -> None:
    global _discount_overrides_cache
    global _discount_overrides_loaded_at
    _discount_overrides_cache = {}
    _discount_overrides_loaded_at = 0.0


def _load_discount_overrides_if_needed(max_age_seconds: int = 60) -> None:
    global _discount_overrides_cache
    global _discount_overrides_loaded_at
    now = time.time()
    if _discount_overrides_loaded_at and now - _discount_overrides_loaded_at < max_age_seconds:
        return

    overrides: dict[str, int] = {}
    try:
        rules: Any = DiscountRule.query.filter_by(active=True).all() # type: ignore
        for rule in rules or []:
            family_id = str(getattr(rule, "family_id", "") or "").strip()
            if not family_id:
                continue
            overrides[family_id] = int(getattr(rule, "percent_off", 0) or 0)
    except Exception:
        # Catalog still works even if the DB isn't ready (e.g., first boot).
        overrides = {}

    _discount_overrides_cache = overrides
    _discount_overrides_loaded_at = now


def get_discount_override_percent(family_id: str) -> Optional[int]:
    _load_discount_overrides_if_needed()
    key = str(family_id or "").strip()
    if not key:
        return None
    if key not in _discount_overrides_cache:
        return None
    return int(_discount_overrides_cache.get(key, 0))


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

    override_discount = get_discount_override_percent(family_id)
    if override_discount is not None:
        discount_percent = max(0, min(int(override_discount), 90))

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

    # Append admin-managed products stored in the database (optional).
    # Note: On Render free plan with SQLite, these rows will reset on redeploy unless you use a persistent DB.
    try:
        admin_products: Any = AdminProduct.query.filter_by(active=True).all() # type: ignore
    except Exception:
        admin_products = []

    if admin_products:
        extra_rows: list[dict[str, Any]] = []
        for product in admin_products:
            extra_rows.append(
                {
                    "product_id": int(getattr(product, "product_id", 0) or 0),
                    "product_family_id": str(getattr(product, "product_family_id", "") or "").strip(),
                    "name": str(getattr(product, "name", "") or "").strip(),
                    "price": float(getattr(product, "price", 0.0) or 0.0),
                    "category": str(getattr(product, "category", "") or "").strip(),
                    "subcategory": str(getattr(product, "subcategory", "") or "").strip(),
                    "brand": str(getattr(product, "brand", "") or "").strip(),
                    "description": str(getattr(product, "description", "") or "").strip(),
                    "variant_type": str(getattr(product, "variant_type", "") or "").strip(),
                    "variant_value": str(getattr(product, "variant_value", "") or "").strip(),
                    "variant_label": str(getattr(product, "variant_label", "") or "").strip(),
                    "is_default": bool(getattr(product, "is_default", True)),
                    "image_url": str(getattr(product, "image_url", "") or "").strip(),
                    "thumb_image_url": str(getattr(product, "thumb_image_url", "") or "").strip(),
                    "hero_image_url": str(getattr(product, "hero_image_url", "") or "").strip(),
                }
            )

        extra_df = pd.DataFrame(extra_rows).fillna("")
        products_df = pd.concat([products_df, extra_df], ignore_index=True)
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
    if payment_method["id"] == "cod":
        payment_status = "Pay on delivery"
        order_status = "confirmed"
    elif payment_method["id"] == "card":
        payment_status = "Awaiting Stripe payment"
        order_status = "pending_payment"
    else:
        payment_status = "Awaiting manual payment confirmation"
        order_status = "confirmed"

    tracking_number = f"TRK-{uuid4().hex[:10].upper()}"
    tracking_url = url_for('track_order', tracking_number=tracking_number, _external=True)

    return {
        "id": f"SM-{uuid4().hex[:8].upper()}",
        "placed_at": datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p"),
        "eta": eta,
        "tracking_number": tracking_number,
        "tracking_url": tracking_url,
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
        "payment_gateway": "stripe" if payment_method["id"] == "card" else "manual",
        "order_status": order_status,
        "items": cart_items,
        "summary": summary,
    }


def save_order(order_payload: dict[str, Any]) -> None:
    orders = session.get("orders", [])
    orders.insert(0, order_payload)
    session["orders"] = orders[:5]
    session["last_order"] = order_payload
    session.modified = True


def order_record_to_payload(order: Order) -> dict[str, Any]:
    tracking_url = url_for("track_order", tracking_number=order.tracking_number, _external=True)
    return {
        "id": order.order_id,
        "placed_at": order.placed_at_display,
        "eta": order.eta,
        "tracking_number": order.tracking_number,
        "tracking_url": tracking_url,
        "customer": {
            "full_name": order.customer_name,
            "email": order.customer_email,
            "phone": order.customer_phone,
            "address": order.customer_address,
            "city": order.customer_city,
            "postal_code": order.customer_postal_code,
        },
        "payment_method": order.payment_method_label,
        "payment_status": order.payment_status,
        "payment_method_id": order.payment_method_id,
        "payment_gateway": order.payment_gateway,
        "payment_reference": order.payment_reference,
        "order_status": order.status,
        "items": list(order.items_json or []),
        "summary": dict(order.summary_json or {}),
    }


def get_order_record_by_order_id(order_id: str) -> Optional[Order]:
    return Order.query.filter_by(order_id=str(order_id).strip()).first() # type: ignore


def get_order_record_by_tracking_number(tracking_number: str) -> Optional[Order]:
    return Order.query.filter_by(tracking_number=str(tracking_number).strip().upper()).first() # type: ignore


def upsert_order_record(order_payload: dict[str, Any], mark_email_sent: bool = False) -> Order:
    order_record = get_order_record_by_order_id(order_payload["id"])
    if order_record is None:
        order_record = Order(order_id=order_payload["id"], tracking_number=order_payload["tracking_number"]) # type: ignore
        db.session.add(order_record) # type: ignore

    customer = order_payload["customer"]
    order_record.user_id = getattr(current_user, "id", None) if current_user.is_authenticated else None # type: ignore
    order_record.customer_name = customer["full_name"]
    order_record.customer_email = customer["email"]
    order_record.customer_phone = customer["phone"]
    order_record.customer_address = customer["address"]
    order_record.customer_city = customer["city"]
    order_record.customer_postal_code = customer["postal_code"]
    order_record.payment_method_id = order_payload["payment_method_id"]
    order_record.payment_method_label = order_payload["payment_method"]
    order_record.payment_status = order_payload["payment_status"]
    order_record.payment_gateway = str(order_payload.get("payment_gateway", "manual"))
    order_record.payment_reference = str(order_payload.get("payment_reference", ""))
    order_record.status = str(order_payload.get("order_status", "processing"))
    order_record.eta = order_payload["eta"]
    order_record.placed_at_display = order_payload["placed_at"]
    order_record.items_json = order_payload["items"]
    order_record.summary_json = order_payload["summary"]
    if mark_email_sent:
        order_record.confirmation_email_sent = True

    db.session.commit() # type: ignore
    return order_record


def update_order_payment_and_status(order_id: str, payment_status: str, order_status: str, payment_reference: str = "") -> None:
    order_record = get_order_record_by_order_id(order_id)
    if order_record is None:
        return

    order_record.payment_status = payment_status
    order_record.status = order_status
    if payment_reference:
        order_record.payment_reference = payment_reference
    db.session.commit() # type: ignore


def mark_order_confirmation_email_sent(order_id: str) -> None:
    order_record = get_order_record_by_order_id(order_id)
    if order_record is None:
        return
    order_record.confirmation_email_sent = True
    db.session.commit() # type: ignore


def create_stripe_checkout_session(order_payload: dict[str, Any]) -> Any:
    if not is_stripe_ready():
        raise RuntimeError("Stripe is not configured.")

    stripe_config = get_stripe_config()
    stripe.api_key = stripe_config["secret_key"] # type: ignore[union-attr]
    line_items: list[dict[str, Any]] = []
    for item in order_payload["items"]:
        unit_amount = max(int(round(float(item["price"]) * 100)), 1)
        line_items.append(
            {
                "price_data": {
                    "currency": stripe_config["currency"],
                    "product_data": {"name": str(item["full_name"])[:120]},
                    "unit_amount": unit_amount,
                },
                "quantity": int(item["quantity"]),
            }
        )

    shipping_amount = float(order_payload["summary"].get("shipping", 0.0) or 0.0)
    if shipping_amount > 0:
        line_items.append(
            {
                "price_data": {
                    "currency": stripe_config["currency"],
                    "product_data": {"name": "Shipping"},
                    "unit_amount": int(round(shipping_amount * 100)),
                },
                "quantity": 1,
            }
        )

    tax_amount = float(order_payload["summary"].get("tax", 0.0) or 0.0)
    if tax_amount > 0:
        line_items.append(
            {
                "price_data": {
                    "currency": stripe_config["currency"],
                    "product_data": {"name": "Tax"},
                    "unit_amount": int(round(tax_amount * 100)),
                },
                "quantity": 1,
            }
        )

    success_url = (
        url_for("stripe_checkout_success", order_id=order_payload["id"], _external=True)
        + "?session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = url_for("stripe_checkout_cancel", order_id=order_payload["id"], _external=True)

    return stripe.checkout.Session.create( # type: ignore[union-attr]
        mode="payment",
        line_items=cast(Any, line_items),
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=order_payload["customer"]["email"],
        metadata={
            "order_id": order_payload["id"],
            "tracking_number": order_payload["tracking_number"],
        },
    )


def get_tracking_history(order_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return build_tracking_timeline(
        str(order_payload.get("order_status", "processing")),
        str(order_payload.get("placed_at", "")),
        str(order_payload.get("eta", "")),
    )


def get_mail_config() -> dict[str, Any]:
    return {
        "resend_api_key": str(os.environ.get("RESEND_API_KEY", "") or "").strip(),
        "smtp_server": str(os.environ.get("MAIL_SERVER", "") or "").strip(),
        "smtp_port": int(str(os.environ.get("MAIL_PORT", "587") or "587").strip() or "587"),
        "smtp_username": str(os.environ.get("MAIL_USERNAME", "") or "").strip(),
        "smtp_password": str(os.environ.get("MAIL_PASSWORD", "") or "").strip(),
        "smtp_use_tls": coerce_bool(os.environ.get("MAIL_USE_TLS", "true")),
        "from_name": str(os.environ.get("MAIL_FROM_NAME", SITE_NAME) or SITE_NAME).strip() or SITE_NAME,
        "from_address": str(os.environ.get("MAIL_FROM_ADDRESS", "onboarding@resend.dev") or "").strip()
        or "onboarding@resend.dev",
    }


def send_html_email_async(subject: str, recipient_email: str, text_content: str, html_content: str) -> None:
    mail = get_mail_config()
    recipient = str(recipient_email or "").strip()

    if not recipient:
        return

    from_address = f"{mail['from_name']} <{mail['from_address']}>"

    resend_api_key = str(mail.get("resend_api_key", "") or "").strip()
    smtp_server = str(mail.get("smtp_server", "") or "").strip()
    smtp_username = str(mail.get("smtp_username", "") or "").strip()
    smtp_password = str(mail.get("smtp_password", "") or "").strip()
    smtp_configured = bool(smtp_server and smtp_username and smtp_password)

    if resend_api_key and resend is not None:
        try:
            resend.api_key = resend_api_key # type: ignore
            resend.Emails.send({ # type: ignore
                "from": from_address,
                "to": recipient,
                "subject": subject,
                "text": text_content,
                "html": html_content
            })
            app.logger.info("Email sent via Resend: %s -> %s", subject, recipient)
            return
        except Exception as exc:
            # Resend free-tier accounts may only send to the account email until a domain is verified.
            # If SMTP is configured, fall back automatically.
            if smtp_configured:
                app.logger.warning("Resend email failed; falling back to SMTP: %s", exc)
            else:
                app.logger.exception("Failed to send email '%s' to %s: %s", subject, recipient, exc)
                return

    if not smtp_configured:
        app.logger.warning(
            "Email disabled: configure RESEND_API_KEY or SMTP (MAIL_SERVER/MAIL_USERNAME/MAIL_PASSWORD)."
        )
        return

    smtp_port = int(mail.get("smtp_port", 587) or 587)
    smtp_use_tls = bool(mail.get("smtp_use_tls", True))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = recipient
    msg.set_content(text_content)
    msg.add_alternative(html_content, subtype="html")

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            if smtp_use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(smtp_username, smtp_password)
            smtp.send_message(msg)
        app.logger.info("Email sent via SMTP: %s -> %s", subject, recipient)
    except Exception as exc:
        app.logger.exception("Failed to send email '%s' to %s: %s", subject, recipient, exc)


def send_order_email_async(order_payload: dict[str, Any], recipient_email: str) -> None:
    items_html = "".join(
        [
            f"<li>{item['quantity']}x {item['full_name']} - {item['price_display']}</li>"
            for item in order_payload["items"]
        ]
    )

    send_html_email_async(
        subject=f"Your ShadowMarket Order {order_payload['id']} is Confirmed",
        recipient_email=recipient_email,
        text_content="Your ShadowMarket order is confirmed. Please open this email in HTML view for full details.",
        html_content=f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Thank you for your order, {order_payload['customer']['full_name']}!</h2>
            <p>We have received your order <strong>{order_payload['id']}</strong> and it is being processed.</p>

            <div style="background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h3 style="margin-top: 0;">Tracking Information</h3>
                <p>Your tracking number is: <strong>{order_payload['tracking_number']}</strong></p>
                <p>
                    Track your package here:
                    <a href="{order_payload['tracking_url']}" style="color: #0066cc;">Track Order</a>
                </p>
                <p>Estimated delivery: <strong>{order_payload['eta']}</strong></p>
            </div>

            <h3>Order Summary</h3>
            <ul>{items_html}</ul>
            <p><strong>Total: {order_payload['summary']['total_display']}</strong></p>
            <p>Thanks for shopping at ShadowMarket.</p>
        </body>
        </html>
        """,
    )


def send_order_email(order_payload: dict[str, Any], recipient_email: str) -> None:
    if recipient_email:
        thread = threading.Thread(target=send_order_email_async, args=(order_payload, recipient_email), daemon=True)
        thread.start()


def send_welcome_email_async(
    recipient_email: str,
    username: str,
    shop_url: str,
    track_url: str,
    support_url: str,
) -> None:
    send_html_email_async(
        subject="Welcome to ShadowMarket",
        recipient_email=recipient_email,
        text_content=(
            f"Welcome to ShadowMarket, {username}!\n\n"
            f"Start shopping: {shop_url}\n"
            f"Track an order: {track_url}\n"
            f"Need help? {support_url}\n\n"
            "If you didn't create this account, you can ignore this email."
        ),
        html_content=f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
                Your account is ready. Browse the catalog, track orders, and reach support anytime.
            </div>
            <div style="max-width: 600px; margin: 0 auto; padding: 22px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color:#000; margin: 0 0 10px 0;">Welcome to ShadowMarket, {username}!</h2>
                <p style="margin:0 0 14px 0;">We’re thrilled to have you on board.</p>

                <div style="background:#f6f6f6; padding:14px 16px; border-radius:8px; margin: 14px 0;">
                    <p style="margin:0 0 10px 0;"><strong>Quick start</strong></p>
                    <ol style="margin:0; padding-left:18px;">
                        <li>Explore the catalog and add items to your cart.</li>
                        <li>Checkout and you’ll get an order confirmation email.</li>
                        <li>Track your delivery anytime using your tracking number.</li>
                    </ol>
                </div>

                <div style="text-align:center; margin: 22px 0 10px 0;">
                    <a href="{shop_url}" style="display:inline-block; padding:12px 22px; background:#000; color:#fff; text-decoration:none; border-radius:6px; font-weight:700;">
                        Start Shopping
                    </a>
                </div>

                <div style="text-align:center; margin: 10px 0 18px 0;">
                    <a href="{track_url}" style="display:inline-block; padding:10px 18px; background:#fff; color:#000; text-decoration:none; border-radius:6px; border:1px solid #000; font-weight:700; margin-right:8px;">
                        Track an Order
                    </a>
                    <a href="{support_url}" style="display:inline-block; padding:10px 18px; background:#fff; color:#000; text-decoration:none; border-radius:6px; border:1px solid #000; font-weight:700;">
                        Contact Support
                    </a>
                </div>

                <p style="margin:0 0 12px 0;">
                    Tip: If you ever receive a login email you don’t recognize, change your password immediately.
                </p>
                <p style="margin:0; color:#666; font-size:12px;">
                    If you didn’t create this account, you can safely ignore this email.
                </p>

                <p style="margin:18px 0 0 0;">Thanks,<br><strong>The ShadowMarket Team</strong></p>
            </div>
        </body>
        </html>
        """,
    )


def send_welcome_email(recipient_email: str, username: str) -> None:
    if recipient_email:
        shop_url = url_for("index", _external=True)
        track_url = url_for("track_order_lookup", _external=True)
        support_url = url_for("support", _external=True)
        thread = threading.Thread(
            target=send_welcome_email_async,
            args=(recipient_email, username, shop_url, track_url, support_url),
            daemon=True,
        )
        thread.start()


def send_login_email_async(recipient_email: str, username: str, login_time: str, shop_url: str) -> None:
    send_html_email_async(
        subject="ShadowMarket login notification",
        recipient_email=recipient_email,
        text_content=f"Hello {username}, your ShadowMarket account just logged in at {login_time} UTC.",
        html_content=f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
                <h2 style="color: #000; margin-bottom: 12px;">New login detected</h2>
                <p>Hello {username}, we noticed a successful login to your ShadowMarket account.</p>
                <p><strong>Time (UTC):</strong> {login_time}</p>
                <p>If this was you, no action is needed. If not, change your password immediately.</p>
                <div style="text-align: center; margin: 26px 0;">
                    <a href="{shop_url}" style="display: inline-block; padding: 12px 24px; background-color: #000; color: #fff; text-decoration: none; border-radius: 5px; font-weight: bold;">Open ShadowMarket</a>
                </div>
                <p>Stay safe,<br><strong>The ShadowMarket Team</strong></p>
            </div>
        </body>
        </html>
        """,
    )


def send_login_email(recipient_email: str, username: str) -> None:
    if not recipient_email:
        return

    send_login_notifications = coerce_bool(os.environ.get("MAIL_SEND_LOGIN_NOTIFICATIONS", "true"))
    if not send_login_notifications:
        return

    login_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    shop_url = url_for("index", _external=True)
    thread = threading.Thread(
        target=send_login_email_async,
        args=(recipient_email, username, login_time, shop_url),
        daemon=True,
    )
    thread.start()


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
    # Keep admin routes fast and isolated: do not force-load the full catalog/recommenders
    # just to render the admin UI.
    if request.path.startswith("/admin"):
        return {
            "site_name": SITE_NAME,
            "categories": [],
            "cart_count": 0,
            "cart_total": format_money(0),
            "footer_year": datetime.now(timezone.utc).year,
            "search_terms": [],
            "placeholder_image": url_for("static", filename="images/product-placeholder.svg"),
            "catalog_stats": {"product_count": 0, "family_count": 0, "category_count": 0},
            "sort_options": SORT_OPTIONS,
        }

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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    cfg = get_admin_config()
    if not cfg.get("enabled", True):
        flash("Admin panel is disabled.", "warning")
        return redirect(url_for("index"))

    expected_email = str(cfg.get("email") or "")
    has_password = bool(cfg.get("password_hash") or cfg.get("password_plain"))
    if not expected_email or not has_password:
        flash("Admin panel is not configured yet.", "warning")
        return redirect(url_for("index"))

    if admin_is_authenticated():
        return redirect(url_for("admin_dashboard"))

    form = AdminLoginForm()
    if form.validate_on_submit():
        ip = _admin_client_ip()
        max_attempts = int(cfg.get("max_attempts", 10) or 10)
        window_seconds = int(cfg.get("window_seconds", 600) or 600)
        if _admin_is_rate_limited(ip, max_attempts, window_seconds):
            flash("Too many failed attempts. Please wait a few minutes and try again.", "danger")
            return render_template("admin/login.html", form=form)

        email = str(form.email.data or "").strip().lower()
        password = str(form.password.data or "")
        if email != expected_email:
            _admin_record_failure(ip)
            flash("Invalid admin credentials.", "danger")
            return render_template("admin/login.html", form=form)

        password_hash = str(cfg.get("password_hash") or "")
        password_plain = str(cfg.get("password_plain") or "")
        ok_password = check_password_hash(password_hash, password) if password_hash else password == password_plain
        if not ok_password:
            _admin_record_failure(ip)
            flash("Invalid admin credentials.", "danger")
            return render_template("admin/login.html", form=form)

        require_2fa = bool(cfg.get("require_2fa", True))
        totp_secret = str(cfg.get("totp_secret") or "")
        totp_code = str(form.totp_code.data or "").strip()
        if require_2fa:
            if pyotp is None or not totp_secret:
                flash("Admin 2FA is not configured (missing pyotp or ADMIN_TOTP_SECRET).", "danger")
                return render_template("admin/login.html", form=form)
            if not _admin_totp_valid(totp_secret, totp_code):
                _admin_record_failure(ip)
                flash("Invalid authenticator code.", "danger")
                return render_template("admin/login.html", form=form)

        session["admin_authed"] = True
        session["admin_email"] = expected_email
        if require_2fa and form.remember.data:
            session["admin_2fa_valid_until"] = int(time.time() + 30 * 24 * 3600)
        else:
            session.pop("admin_2fa_valid_until", None)

        admin_audit("login", target_type="admin", target_id=expected_email, detail="Admin signed in")
        flash("Signed in to admin.", "success")
        next_path = str(request.args.get("next") or "").strip()
        if next_path.startswith("/") and not next_path.startswith("//"):
            return redirect(next_path)
        return redirect(url_for("admin_dashboard"))
    elif request.method == "POST":
        flash("Please complete the admin login form correctly.", "warning")

    return render_template("admin/login.html", form=form)


@app.route("/admin/logout")
def admin_logout():
    if session.get("admin_authed"):
        admin_audit("logout", target_type="admin", target_id=str(session.get("admin_email") or ""), detail="Admin signed out")
    session.pop("admin_authed", None)
    session.pop("admin_email", None)
    session.pop("admin_2fa_valid_until", None)
    flash("Admin signed out.", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    # Analytics metrics
    total_orders = Order.query.count() # type: ignore
    total_revenue = sum(float(o.summary_json.get("total_price", 0)) for o in Order.query.all() if hasattr(o, "summary_json")) # type: ignore
    delivered_orders = Order.query.filter_by(status="delivered").count() # type: ignore
    open_tickets_count = SupportTicket.query.filter_by(status="open").count() # type: ignore
    
    # Recent data
    recent_orders: Any = Order.query.order_by(Order.created_at.desc()).limit(10).all() # type: ignore
    open_tickets: Any = SupportTicket.query.filter_by(status="open").order_by(SupportTicket.created_at.desc()).limit(10).all() # type: ignore
    discounts: Any = DiscountRule.query.order_by(DiscountRule.updated_at.desc()).limit(10).all() # type: ignore
    audit: Any = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(10).all() # type: ignore

    return render_template(
        "admin/dashboard.html",
        total_orders=total_orders,
        total_revenue=round(total_revenue, 2),
        delivered_orders=delivered_orders,
        open_tickets_count=open_tickets_count,
        recent_orders=recent_orders,
        open_tickets=open_tickets,
        discounts=discounts,
        audit=audit,
    )


@app.route("/admin/orders")
@admin_required
def admin_orders():
    order_records: Any = Order.query.order_by(Order.created_at.desc()).limit(100).all() # type: ignore
    return render_template("admin/orders.html", orders=order_records)


@app.route("/admin/orders/<order_id>", methods=["GET", "POST"])
@admin_required
def admin_order_detail(order_id: str):
    order_record = get_order_record_by_order_id(order_id)
    if order_record is None:
        flash("Order not found.", "warning")
        return redirect(url_for("admin_orders"))

    form = AdminOrderStatusForm(status=str(order_record.status or "processing"))
    if form.validate_on_submit():
        previous_status = str(order_record.status or "")
        order_record.status = str(form.status.data or "processing")  # type: ignore
        db.session.commit() # type: ignore
        admin_audit(
            "order_status_update",
            target_type="order",
            target_id=str(order_record.order_id),
            detail=f"{previous_status} -> {order_record.status}. {str(form.note.data or '').strip()}",
        )
        flash("Order updated.", "success")
        return redirect(url_for("admin_order_detail", order_id=order_id))

    order_payload = order_record_to_payload(order_record)
    tracking_timeline = get_tracking_history(order_payload)
    return render_template(
        "admin/order_detail.html",
        order=order_payload,
        order_record=order_record,
        tracking_timeline=tracking_timeline,
        form=form,
    )


@app.route("/admin/tickets")
@admin_required
def admin_tickets():
    tickets: Any = SupportTicket.query.order_by(SupportTicket.created_at.desc()).limit(200).all() # type: ignore
    return render_template("admin/tickets.html", tickets=tickets)


@app.route("/admin/tickets/<ticket_id>", methods=["GET", "POST"])
@admin_required
def admin_ticket_detail(ticket_id: str):
    ticket: Any = SupportTicket.query.filter_by(ticket_id=str(ticket_id).strip()).first() # type: ignore
    if ticket is None:
        flash("Ticket not found.", "warning")
        return redirect(url_for("admin_tickets"))

    form = AdminTicketUpdateForm(status=str(getattr(ticket, "status", "open") or "open"))
    if form.validate_on_submit():
        previous_status = str(getattr(ticket, "status", "") or "")
        ticket.status = str(form.status.data or "open")  # type: ignore
        db.session.commit() # type: ignore
        admin_audit(
            "ticket_update",
            target_type="ticket",
            target_id=str(ticket.ticket_id),
            detail=f"{previous_status} -> {ticket.status}. {str(form.note.data or '').strip()}",
        )
        flash("Ticket updated.", "success")
        return redirect(url_for("admin_ticket_detail", ticket_id=ticket_id))

    linked_order = get_order_record_by_order_id(str(getattr(ticket, "order_id", "") or ""))
    return render_template("admin/ticket_detail.html", ticket=ticket, linked_order=linked_order, form=form)


@app.route("/admin/discounts", methods=["GET", "POST"])
@admin_required
def admin_discounts():
    form = AdminDiscountForm()
    if form.validate_on_submit():
        family_id = str(form.family_id.data or "").strip()
        percent_off = int(form.percent_off.data or 0)
        active = bool(form.active.data)

        rule: Any = DiscountRule.query.filter_by(family_id=family_id).first() # type: ignore
        created = False
        if rule is None:
            rule = DiscountRule(family_id=family_id) # type: ignore
            db.session.add(rule) # type: ignore
            created = True

        rule.percent_off = percent_off  # type: ignore
        rule.active = active  # type: ignore
        db.session.commit() # type: ignore

        invalidate_discount_overrides()
        global catalog_ready
        catalog_ready = False

        admin_audit(
            "discount_upsert",
            target_type="discount",
            target_id=family_id,
            detail=f"{'created' if created else 'updated'} percent={percent_off} active={active}",
        )
        flash("Discount saved.", "success")
        return redirect(url_for("admin_discounts"))

    rules: Any = DiscountRule.query.order_by(DiscountRule.updated_at.desc()).all() # type: ignore
    return render_template("admin/discounts.html", rules=rules, form=form)


@app.route("/admin/products")
@admin_required
def admin_products():
    products: Any = AdminProduct.query.order_by(AdminProduct.updated_at.desc()).all() # type: ignore
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def admin_product_new():
    form = AdminProductForm()
    if form.validate_on_submit():
        ensure_catalog_loaded()
        next_product_id = int(products_df["product_id"].max()) + 1 if products_df is not None and not products_df.empty else 1 # type: ignore

        record = AdminProduct(
            product_id=next_product_id,  # type: ignore[call-arg]
            product_family_id=str(form.product_family_id.data or "").strip(),  # type: ignore[call-arg]
            name=str(form.name.data or "").strip(),  # type: ignore[call-arg]
            price=float(form.price.data or 0.0),  # type: ignore[call-arg]
            category=str(form.category.data or "").strip(),  # type: ignore[call-arg]
            subcategory=str(form.subcategory.data or "").strip(),  # type: ignore[call-arg]
            brand=str(form.brand.data or "").strip(),  # type: ignore[call-arg]
            description=str(form.description.data or "").strip(),  # type: ignore[call-arg]
            variant_type=str(form.variant_type.data or "").strip(),  # type: ignore[call-arg]
            variant_value=str(form.variant_value.data or "").strip(),  # type: ignore[call-arg]
            variant_label=str(form.variant_label.data or "").strip(),  # type: ignore[call-arg]
            is_default=bool(form.is_default.data),  # type: ignore[call-arg]
            image_url=str(form.image_url.data or "").strip(),  # type: ignore[call-arg]
            thumb_image_url=str(form.image_url.data or "").strip(),  # type: ignore[call-arg]
            hero_image_url=str(form.image_url.data or "").strip(),  # type: ignore[call-arg]
            active=bool(form.active.data),  # type: ignore[call-arg]
        )
        db.session.add(record) # type: ignore
        db.session.commit() # type: ignore

        global catalog_ready
        catalog_ready = False
        admin_audit("product_create", target_type="product", target_id=str(next_product_id), detail=record.name)
        flash("Product added (stored in DB).", "success")
        return redirect(url_for("admin_products"))

    return render_template("admin/product_edit.html", form=form, product=None)


@app.route("/admin/products/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_product_edit(product_id: int):
    product: Any = AdminProduct.query.filter_by(product_id=int(product_id)).first() # type: ignore
    if product is None:
        flash("Admin product not found.", "warning")
        return redirect(url_for("admin_products"))

    form = AdminProductForm(
        name=str(product.name or ""),
        product_family_id=str(product.product_family_id or ""),
        category=str(product.category or ""),
        subcategory=str(product.subcategory or ""),
        brand=str(product.brand or ""),
        description=str(product.description or ""),
        price=float(product.price or 0.0),
        image_url=str(product.image_url or ""),
        variant_label=str(product.variant_label or ""),
        is_default=bool(product.is_default),
        active=bool(product.active),
    )
    if form.validate_on_submit():
        product.product_family_id = str(form.product_family_id.data or "").strip()  # type: ignore
        product.name = str(form.name.data or "").strip()  # type: ignore
        product.price = float(form.price.data or 0.0)  # type: ignore
        product.category = str(form.category.data or "").strip()  # type: ignore
        product.subcategory = str(form.subcategory.data or "").strip()  # type: ignore
        product.brand = str(form.brand.data or "").strip()  # type: ignore
        product.description = str(form.description.data or "").strip()  # type: ignore
        product.variant_label = str(form.variant_label.data or "").strip()  # type: ignore
        product.is_default = bool(form.is_default.data)  # type: ignore
        product.active = bool(form.active.data)  # type: ignore
        image_url = str(form.image_url.data or "").strip()
        product.image_url = image_url  # type: ignore
        product.thumb_image_url = image_url  # type: ignore
        product.hero_image_url = image_url  # type: ignore
        db.session.commit() # type: ignore

        global catalog_ready
        catalog_ready = False
        admin_audit("product_update", target_type="product", target_id=str(product_id), detail=product.name)
        flash("Product updated.", "success")
        return redirect(url_for("admin_product_edit", product_id=product_id))

    return render_template("admin/product_edit.html", form=form, product=product)


@app.route("/admin/audit")
@admin_required
def admin_audit_log():
    entries: Any = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(300).all() # type: ignore
    return render_template("admin/audit.html", entries=entries)


@app.route("/admin/analytics")
@admin_required
def admin_analytics():
    from datetime import datetime, timedelta
    
    # Overall stats
    total_orders = Order.query.count() # type: ignore
    total_revenue = sum(float(o.summary_json.get("total_price", 0)) for o in Order.query.all() if hasattr(o, "summary_json")) # type: ignore
    delivered_orders = Order.query.filter_by(status="delivered").count() # type: ignore
    pending_orders = Order.query.filter_by(status="processing").count() # type: ignore
    open_tickets = SupportTicket.query.filter_by(status="open").count() # type: ignore
    registered_users = User.query.count() # type: ignore
    total_products = AdminProduct.query.count() # type: ignore
    active_products = AdminProduct.query.filter_by(active=True).count() # type: ignore
    
    # Revenue by status
    status_breakdown = {}
    for status in ["pending_payment", "confirmed", "processing", "shipped", "out_for_delivery", "delivered"]:
        orders_with_status = Order.query.filter_by(status=status).all() # type: ignore
        revenue = sum(float(o.summary_json.get("total_price", 0)) for o in orders_with_status if hasattr(o, "summary_json"))
        status_breakdown[status] = {
            "count": len(orders_with_status),
            "revenue": round(revenue, 2)
        }
    
    # Last 7 days orders
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_orders = Order.query.filter(Order.created_at >= seven_days_ago).all() # type: ignore
    recent_revenue = sum(float(o.summary_json.get("total_price", 0)) for o in recent_orders if hasattr(o, "summary_json"))
    
    # Top products by order count
    all_orders = Order.query.all() # type: ignore
    product_counts = {}
    for order in all_orders:
        if hasattr(order, "items_json") and order.items_json:
            for item in order.items_json:
                product_name = item.get("name", "Unknown")
                product_counts[product_name] = product_counts.get(product_name, 0) + item.get("quantity", 1)
    
    top_products = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return render_template(
        "admin/analytics.html",
        total_orders=total_orders,
        total_revenue=round(total_revenue, 2),
        delivered_orders=delivered_orders,
        pending_orders=pending_orders,
        open_tickets=open_tickets,
        registered_users=registered_users,
        total_products=total_products,
        active_products=active_products,
        status_breakdown=status_breakdown,
        recent_orders_count=len(recent_orders),
        recent_revenue=round(recent_revenue, 2),
        top_products=top_products,
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
            send_login_email(user.email, user.username) # type: ignore
            flash("Welcome back to ShadowMarket.", "success")
            return redirect(url_for("index"))
        flash("Invalid username or password.", "warning")
    elif request.method == "POST":
        flash("Please complete the login form correctly.", "warning")

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

        # Send a welcome email in the background
        send_welcome_email(user.email, user.username) # type: ignore

        flash("Account created successfully. Please sign in.", "success")
        return redirect(url_for("login"))
    elif request.method == "POST":
        flash("Please fix the highlighted signup fields and try again.", "warning")

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
        elif form_data["payment_method"] == "card" and not is_stripe_ready():
            flash("Card checkout is temporarily unavailable. Configure Stripe keys to enable it.", "warning")
        elif form_data["payment_method"] == "netbanking" and not form_data["bank_name"]:
            flash("Please choose a bank for net banking.", "warning")
        else:
            order_payload = build_order_payload(cart_items, cart_summary, form_data)
            save_order(order_payload)
            upsert_order_record(order_payload)

            if form_data["payment_method"] == "card":
                if not is_stripe_ready():
                    flash("Stripe is not configured yet. Add STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY to enable card checkout.", "warning")
                    return render_template(
                        "checkout.html",
                        cart_items=cart_items,
                        cart_summary=cart_summary,
                        payment_methods=PAYMENT_METHODS,
                        form_data=form_data,
                        stripe_ready=False,
                    )

                try:
                    stripe_session = create_stripe_checkout_session(order_payload)
                    order_payload["payment_reference"] = str(getattr(stripe_session, "id", ""))
                    upsert_order_record(order_payload)
                    session["pending_order_id"] = order_payload["id"]
                    session.modified = True
                    checkout_url = str(getattr(stripe_session, "url", "")).strip()
                    if not checkout_url:
                        raise RuntimeError("Stripe did not return a checkout URL.")
                    return redirect(checkout_url, code=303)
                except Exception as exc:
                    app.logger.error("Stripe checkout creation failed for %s: %s", order_payload["id"], exc)
                    flash("Could not start Stripe checkout. Please try again or choose another payment method.", "danger")
                    return render_template(
                        "checkout.html",
                        cart_items=cart_items,
                        cart_summary=cart_summary,
                        payment_methods=PAYMENT_METHODS,
                        form_data=form_data,
                        stripe_ready=is_stripe_ready(),
                    )

            order_payload["order_status"] = "processing"
            if form_data["payment_method"] != "cod":
                order_payload["payment_status"] = "Payment submitted"

            record_order_interactions(cart_items)
            upsert_order_record(order_payload)
            save_cart_map({})
            send_order_email(order_payload, form_data["email"])
            mark_order_confirmation_email_sent(order_payload["id"])

            flash("Order placed successfully.", "success")
            return redirect(url_for("order_success", order_id=order_payload["id"]))

    return render_template(
        "checkout.html",
        cart_items=cart_items,
        cart_summary=cart_summary,
        payment_methods=PAYMENT_METHODS,
        form_data=form_data,
        stripe_ready=is_stripe_ready(),
    )


@app.route("/checkout/stripe-success/<order_id>")
def stripe_checkout_success(order_id: str):
    order_record = get_order_record_by_order_id(order_id)
    if order_record is None:
        flash("That Stripe checkout session is not linked to an order.", "warning")
        return redirect(url_for("checkout"))

    order_payload = order_record_to_payload(order_record)
    session_id = str(request.args.get("session_id", "")).strip()
    if not session_id:
        flash("Payment session could not be verified.", "warning")
        return redirect(url_for("checkout"))

    if not is_stripe_ready():
        flash("Stripe is not configured on this server.", "warning")
        return redirect(url_for("checkout"))

    try:
        stripe_config = get_stripe_config()
        stripe.api_key = stripe_config["secret_key"] # type: ignore[union-attr]
        checkout_session = stripe.checkout.Session.retrieve(session_id) # type: ignore[union-attr]
        payment_status = str(getattr(checkout_session, "payment_status", "unpaid")).lower()
    except Exception as exc:
        app.logger.error("Stripe session verification failed for %s: %s", order_id, exc)
        flash("We could not verify payment yet. Please contact support if your card was charged.", "danger")
        return redirect(url_for("checkout"))

    if payment_status != "paid":
        flash("Payment is still pending. Please complete checkout in Stripe.", "warning")
        return redirect(url_for("checkout"))

    update_order_payment_and_status(
        order_id,
        payment_status="Paid via Stripe",
        order_status="processing",
        payment_reference=session_id,
    )

    order_payload["payment_status"] = "Paid via Stripe"
    order_payload["payment_reference"] = session_id
    order_payload["order_status"] = "processing"
    save_order(order_payload)

    record_order_interactions(order_payload["items"])
    save_cart_map({})

    if not order_record.confirmation_email_sent:
        send_order_email(order_payload, order_payload["customer"]["email"])
        mark_order_confirmation_email_sent(order_payload["id"])

    flash("Payment confirmed. Your order is now processing.", "success")
    return redirect(url_for("order_success", order_id=order_id))


@app.route("/checkout/stripe-cancel/<order_id>")
def stripe_checkout_cancel(order_id: str):
    order_record = get_order_record_by_order_id(order_id)
    if order_record is not None:
        update_order_payment_and_status(
            order_id,
            payment_status="Stripe checkout canceled",
            order_status="pending_payment",
            payment_reference=order_record.payment_reference,
        )
    flash("Stripe checkout canceled. You can retry card payment or choose another method.", "info")
    return redirect(url_for("checkout"))


@app.route("/order-success/<order_id>")
def order_success(order_id: str):
    order_record = get_order_record_by_order_id(order_id)
    order_payload: Optional[dict[str, Any]] = order_record_to_payload(order_record) if order_record is not None else None
    if order_payload is None:
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
    tracking_timeline = get_tracking_history(order_payload)
    return render_template(
        "order_success.html",
        order=order_payload,
        tracking_timeline=tracking_timeline,
        recommended_products=recommended_products,
    )


@app.route("/track", methods=["GET", "POST"])
def track_order_lookup():
    if request.method == "POST":
        tracking_number = str(request.form.get("tracking_number", "")).strip().upper()
        if not tracking_number:
            flash("Enter a tracking number to continue.", "warning")
            return redirect(url_for("track_order_lookup"))
        return redirect(url_for("track_order", tracking_number=tracking_number))

    recent_orders: list[dict[str, Any]] = []
    if current_user.is_authenticated: # type: ignore
        order_records: Any = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).limit(5).all() # type: ignore
        recent_orders = [order_record_to_payload(order_record) for order_record in order_records]

    return render_template(
        "track_order.html",
        order=None,
        tracking_timeline=[],
        recent_orders=recent_orders,
        entered_tracking_number="",
    )


@app.route("/track/<tracking_number>")
def track_order(tracking_number: str):
    tracking_number = str(tracking_number).strip().upper()
    order_record = get_order_record_by_tracking_number(tracking_number)
    order_payload: Optional[dict[str, Any]] = order_record_to_payload(order_record) if order_record is not None else None

    if order_payload is None:
        session_order = next(
            (order for order in session.get("orders", []) if str(order.get("tracking_number", "")).upper() == tracking_number),
            None,
        )
        order_payload = session_order if isinstance(session_order, dict) else None

    if order_payload is None:
        flash(f"No order found with tracking number {tracking_number}.", "warning")
        return redirect(url_for("track_order_lookup"))

    tracking_timeline = get_tracking_history(order_payload)
    return render_template(
        "track_order.html",
        order=order_payload,
        tracking_timeline=tracking_timeline,
        recent_orders=[],
        entered_tracking_number=tracking_number,
    )


@app.route("/support", methods=["GET", "POST"])
def support():
    order_id = str(request.values.get("order_id", "")).strip()
    tracking_number = str(request.values.get("tracking_number", "")).strip().upper()
    linked_order = get_order_record_by_order_id(order_id) if order_id else None
    if linked_order is None and tracking_number:
        linked_order = get_order_record_by_tracking_number(tracking_number)

    form_data: dict[str, str] = {
        "full_name": getattr(current_user, "username", "") if current_user.is_authenticated else "", # type: ignore
        "email": getattr(current_user, "email", "") if current_user.is_authenticated else "", # type: ignore
        "subject": "",
        "message": "",
        "order_id": linked_order.order_id if linked_order is not None else order_id,
        "tracking_number": linked_order.tracking_number if linked_order is not None else tracking_number,
    }

    created_ticket: Optional[SupportTicket] = None

    if request.method == "POST":
        for key in form_data:
            form_data[key] = str(request.form.get(key, "")).strip()

        required_fields = ["full_name", "email", "subject", "message"]
        missing_fields = [field for field in required_fields if not form_data[field]]
        if missing_fields:
            flash("Please complete all required support fields.", "warning")
        else:
            ticket = SupportTicket(
                ticket_id=f"SUP-{uuid4().hex[:8].upper()}", # type: ignore
                user_id=getattr(current_user, "id", None) if current_user.is_authenticated else None, # type: ignore
                order_id=form_data["order_id"], # type: ignore
                tracking_number=form_data["tracking_number"], # type: ignore
                customer_name=form_data["full_name"], # type: ignore
                customer_email=form_data["email"], # type: ignore
                subject=form_data["subject"], # type: ignore
                message=form_data["message"], # type: ignore
                status="open", # type: ignore
            )
            db.session.add(ticket) # type: ignore
            db.session.commit() # type: ignore
            created_ticket = ticket
            flash(f"Support ticket {ticket.ticket_id} created successfully.", "success")

            thread = threading.Thread(
                target=send_html_email_async,
                kwargs={
                    "subject": f"Support ticket {ticket.ticket_id} received",
                    "recipient_email": ticket.customer_email,
                    "text_content": f"We have received your request ({ticket.ticket_id}). Our team will contact you shortly.",
                    "html_content": f"""
                    <html>
                    <body style=\"font-family: Arial, sans-serif; color: #333;\">
                        <h2>Support request received</h2>
                        <p>Hi {ticket.customer_name}, your support ticket <strong>{ticket.ticket_id}</strong> is now open.</p>
                        <p><strong>Subject:</strong> {ticket.subject}</p>
                        <p>We will respond soon. You can reference this ticket ID anytime.</p>
                    </body>
                    </html>
                    """,
                },
                daemon=True,
            )
            thread.start()

    recent_tickets: list[SupportTicket] = []
    if current_user.is_authenticated: # type: ignore
        recent_tickets = SupportTicket.query.filter_by(user_id=current_user.id).order_by(SupportTicket.created_at.desc()).limit(6).all() # type: ignore
    elif form_data["email"]:
        recent_tickets = SupportTicket.query.filter_by(customer_email=form_data["email"]).order_by(SupportTicket.created_at.desc()).limit(6).all() # type: ignore

    return render_template(
        "support.html",
        form_data=form_data,
        linked_order=order_record_to_payload(linked_order) if linked_order is not None else None,
        created_ticket=created_ticket,
        recent_tickets=recent_tickets,
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
