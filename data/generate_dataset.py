import csv
import os
import random
import re
from urllib.parse import quote
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

PRODUCTS_FILE = os.path.join(DATA_DIR, "products.csv")
INTERACTIONS_FILE = os.path.join(DATA_DIR, "interactions.csv")


def unsplash_image(photo_id):
    base = f"https://images.unsplash.com/{photo_id}"
    return {
        "thumb": f"{base}?auto=format&fit=crop&w=720&h=720&q=80",
        "hero": f"{base}?auto=format&fit=crop&w=1280&h=1280&q=82",
    }


IMAGE_LIBRARY = {
    "phone_graphite": unsplash_image("photo-1511707171634-5f897ff02aa9"),
    "phone_blue": unsplash_image("photo-1592286927505-1def25e5cefd"),
    "phone_gold": unsplash_image("photo-1611707267537-b85faf00021a"),
    "phone_white": unsplash_image("photo-1598327105666-5b89351aff97"),
    "laptop_clean": unsplash_image("photo-1517694712202-14dd9538aa97"),
    "laptop_dark": unsplash_image("photo-1496181133206-80ce9b88a853"),
    "headphones": unsplash_image("photo-1505740420928-5e560c06d30e"),
    "earbuds": unsplash_image("photo-1606841837239-c5a1a8a07af7"),
    "watch": unsplash_image("photo-1523275335684-37898b6baf30"),
    "tablet": unsplash_image("photo-1544716278-ca5e3af564d7"),
    "console": unsplash_image("photo-1516905041604-bbb0f8ab9c38"),
    "camera": unsplash_image("photo-1516035069371-29a1b244cc32"),
    "sneaker_red": unsplash_image("photo-1542291026-7eec264c27ff"),
    "denim": unsplash_image("photo-1542272604-787c62d465d1"),
    "dress": unsplash_image("photo-1543162521-9efac4ce7531"),
    "coat": unsplash_image("photo-1539533057440-7ce297ca0ed0"),
    "hoodie": unsplash_image("photo-1556821552-9f6db051b1da"),
    "jacket": unsplash_image("photo-1551028719-00167b16ebc5"),
    "handbag": unsplash_image("photo-1584917865442-de89df76afd3"),
    "kitchen": unsplash_image("photo-1556909114-f6e7ad7d3136"),
    "mixer": unsplash_image("photo-1578500494198-246f612d03b3"),
    "coffee": unsplash_image("photo-1517668808822-9ebb02ae2a0e"),
    "vacuum": unsplash_image("photo-1585771724684-38269d6639fd"),
    "books_stack": unsplash_image("photo-1512820790803-83ca734da794"),
    "books_open": unsplash_image("photo-1507842072343-583f20270319"),
    "bike": unsplash_image("photo-1534438327276-14e5300c3a48"),
    "yoga": unsplash_image("photo-1506241537724-992ce8e5a5b0"),
    "serum": unsplash_image("photo-1556228578-8c89e6adf883"),
    "beauty_tools": unsplash_image("photo-1517440467454-df4628965ba0"),
    "fragrance": unsplash_image("photo-1596462502278-27bfdc403348"),
    "lego": unsplash_image("photo-1611987867914-5c7947a0b1a3"),
    "boardgame": unsplash_image("photo-1552820728-8209b6beb5e3"),
}

CATEGORY_QUERY_HINTS = {
    "Mobiles": ["smartphone", "mobile", "technology"],
    "Electronics": ["electronics", "gadgets", "technology"],
    "Fashion": ["fashion", "style", "apparel"],
    "Home & Kitchen": ["kitchen", "home", "appliance"],
    "Books": ["books", "reading", "library"],
    "Sports & Fitness": ["fitness", "sports", "workout"],
    "Beauty & Personal Care": ["beauty", "cosmetics", "skincare"],
    "Toys & Games": ["toys", "games", "play"],
}

SUBCATEGORY_QUERY_HINTS = {
    "Gaming Phones": ["gaming phone", "rgb"],
    "Headphones": ["headphones", "audio"],
    "Tablets": ["tablet", "screen"],
    "Action Cameras": ["action camera", "outdoor"],
    "Dolls & Playsets": ["doll", "playset", "kids toy"],
    "Board Games": ["board game", "tabletop"],
    "Party Games": ["party game", "friends"],
    "RC Toys": ["remote control toy", "racing"],
    "Action Toys": ["blaster toy", "action toy"],
    "Puzzles": ["puzzle", "jigsaw"],
    "Coffee": ["coffee", "espresso"],
    "Hair Care": ["hair care", "salon"],
    "Skincare": ["skincare", "serum"],
    "Makeup": ["makeup", "cosmetics"],
    "Wearables": ["smartwatch", "fitness watch"],
    "Strength Training": ["dumbbell", "gym"],
    "Recovery": ["recovery", "massage gun"],
    "Outdoor Gear": ["outdoor", "adventure"],
}

STOPWORD_TOKENS = {
    "and",
    "for",
    "the",
    "with",
    "set",
    "kit",
    "edition",
    "ultra",
    "pro",
    "max",
    "plus",
    "new",
    "mini",
}


def collect_query_tokens(*values):
    tokens = []
    for value in values:
        for raw_token in re.findall(r"[A-Za-z0-9']+", str(value).lower()):
            token = raw_token.strip("'")
            if not token or token in STOPWORD_TOKENS:
                continue
            if token.isdigit() or len(token) <= 2:
                continue
            if token not in tokens:
                tokens.append(token)
    return tokens


def name_based_image(family_id, name, brand, category, subcategory):
    query_tokens = collect_query_tokens(name, brand)
    query_tokens.extend(
        token
        for token in collect_query_tokens(*(SUBCATEGORY_QUERY_HINTS.get(subcategory, [])))
        if token not in query_tokens
    )
    query_tokens.extend(
        token
        for token in collect_query_tokens(*(CATEGORY_QUERY_HINTS.get(category, [])))
        if token not in query_tokens
    )

    query = quote(",".join(query_tokens[:7] or ["shopping", "product"]), safe=",")
    seed = sum(ord(char) for char in f"{family_id}|{name}|{category}|{subcategory}") % 5000
    return {
        "thumb": f"https://loremflickr.com/720/720/{query}?lock={seed}",
        "hero": f"https://loremflickr.com/1280/1280/{query}?lock={seed}",
    }


def option(label, price, value=None, default=False):
    return {
        "label": label,
        "value": value or label,
        "price": float(price),
        "default": default,
    }


def family(
    family_id,
    name,
    category,
    brand,
    subcategory,
    description,
    image_key,
    variants,
    variant_type="",
):
    if image_key in IMAGE_LIBRARY:
        images = IMAGE_LIBRARY[image_key]
    else:
        images = name_based_image(family_id, name, brand, category, subcategory)
    return {
        "family_id": family_id,
        "name": name,
        "category": category,
        "brand": brand,
        "subcategory": subcategory,
        "description": description,
        "variant_type": variant_type,
        "variants": variants,
        "images": images,
    }


def build_families():
    return [
        family(
            "mobile-apple-iphone-15-pro",
            "Apple iPhone 15 Pro Max",
            "Mobiles",
            "Apple",
            "Smartphones",
            "Titanium flagship with an advanced camera system, premium battery life, and all-day performance.",
            "phone_graphite",
            [
                option("256GB / Black Titanium", 1199, default=True),
                option("256GB / Blue Titanium", 1199),
                option("512GB / Natural Titanium", 1399),
                option("1TB / White Titanium", 1599),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-samsung-galaxy-s24",
            "Samsung Galaxy S24 Ultra",
            "Mobiles",
            "Samsung",
            "Smartphones",
            "Big-screen Android flagship with AI tools, S Pen productivity, and a high-end zoom camera system.",
            "phone_gold",
            [
                option("256GB / Titanium Gray", 1299, default=True),
                option("512GB / Titanium Violet", 1419),
                option("512GB / Titanium Black", 1419),
                option("1TB / Titanium Yellow", 1659),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-google-pixel-8",
            "Google Pixel 8 Pro",
            "Mobiles",
            "Google",
            "Smartphones",
            "Camera-first smartphone with smart editing tools, clean Android, and dependable daily performance.",
            "phone_white",
            [
                option("128GB / Obsidian", 999, default=True),
                option("256GB / Bay", 1099),
                option("256GB / Porcelain", 1099),
                option("512GB / Mint", 1219),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-oneplus-12",
            "OnePlus 12",
            "Mobiles",
            "OnePlus",
            "Smartphones",
            "Fast flagship with a bright display, rapid charging, and premium hardware for power users.",
            "phone_blue",
            [
                option("256GB / Flowy Emerald", 799, default=True),
                option("256GB / Silky Black", 799),
                option("512GB / Glacial White", 899),
                option("512GB / Crimson Edition", 919),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-nothing-phone-2",
            "Nothing Phone 2",
            "Mobiles",
            "Nothing",
            "Smartphones",
            "Design-forward Android phone with glyph lighting, a clean OS, and standout everyday usability.",
            "phone_white",
            [
                option("128GB / White", 599, default=True),
                option("256GB / Dark Gray", 699),
                option("256GB / Glyph Blue", 719),
                option("512GB / Limited Black", 849),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-xiaomi-14",
            "Xiaomi 14 Ultra",
            "Mobiles",
            "Xiaomi",
            "Smartphones",
            "Photography-focused premium phone with Leica-tuned cameras and a large flagship battery.",
            "phone_gold",
            [
                option("256GB / Black", 999, default=True),
                option("512GB / White", 1099),
                option("512GB / Olive", 1119),
                option("1TB / Titanium Gray", 1299),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-sony-xperia-1-v",
            "Sony Xperia 1 V",
            "Mobiles",
            "Sony",
            "Smartphones",
            "Creator-friendly phone with pro camera controls, cinematic display quality, and premium audio features.",
            "phone_graphite",
            [
                option("256GB / Black", 1249, default=True),
                option("256GB / Khaki Green", 1249),
                option("512GB / Platinum Silver", 1399),
                option("512GB / Creator Black", 1429),
            ],
            "Storage + Finish",
        ),
        family(
            "electronics-macbook-air-m3",
            "MacBook Air M3",
            "Electronics",
            "Apple",
            "Laptops",
            "Ultra-light laptop built for students and creators who want fast daily performance and a premium finish.",
            "laptop_clean",
            [
                option("13-inch / 8GB / 256GB / Starlight", 1299, default=True),
                option("13-inch / 16GB / 512GB / Midnight", 1599),
                option("15-inch / 16GB / 512GB / Silver", 1849),
                option("15-inch / 24GB / 1TB / Space Gray", 2149),
            ],
            "Config + Finish",
        ),
        family(
            "electronics-dell-xps-13",
            "Dell XPS 13 Plus",
            "Electronics",
            "Dell",
            "Laptops",
            "Minimal premium laptop with edge-to-edge design and serious productivity specs for daily work.",
            "laptop_dark",
            [
                option("FHD / 16GB / 512GB / Graphite", 1299, default=True),
                option("Core Ultra 7 / 16GB / 512GB / Platinum", 1399),
                option("OLED / 32GB / 1TB / Graphite", 1699),
                option("OLED / 32GB / 1TB / Platinum", 1799),
            ],
            "Config + Finish",
        ),
        family(
            "electronics-sony-wh1000xm5",
            "Sony WH-1000XM5",
            "Electronics",
            "Sony",
            "Headphones",
            "Noise-canceling over-ear headphones with refined tuning, travel-ready comfort, and long battery life.",
            "headphones",
            [
                option("Black", 399, default=True),
                option("Silver", 399),
                option("Midnight Blue", 419),
                option("Smoky Rose", 419),
            ],
            "Finish",
        ),
        family(
            "electronics-ipad-air-m2",
            "iPad Air M2",
            "Electronics",
            "Apple",
            "Tablets",
            "Thin and powerful tablet for study, sketching, and presentations with all-day battery life.",
            "tablet",
            [
                option("11-inch / 128GB / Space Gray", 699, default=True),
                option("11-inch / 256GB / Blue", 799),
                option("13-inch / 256GB / Starlight", 999),
                option("13-inch / 512GB / Purple", 1299),
            ],
            "Size + Storage",
        ),
        family(
            "electronics-playstation-5",
            "PlayStation 5 Slim",
            "Electronics",
            "Sony",
            "Gaming Consoles",
            "Next-gen console with quick load times, premium visuals, and bundle options for a ready-to-demo setup.",
            "console",
            [
                option("Digital Edition", 499, default=True),
                option("Disc Edition", 549),
                option("Disc + DualSense Bundle", 599),
                option("Disc + Sports Bundle", 619),
            ],
            "Bundle",
        ),
        family(
            "electronics-canon-eos-r6",
            "Canon EOS R6 Mark II",
            "Electronics",
            "Canon",
            "Cameras",
            "Hybrid mirrorless camera made for video creators, photographers, and polished portfolio work.",
            "camera",
            [
                option("Body Only", 2299, default=True),
                option("24-105mm Kit", 2799),
                option("Creator Bundle", 2899),
                option("Travel Bundle", 2999),
            ],
            "Bundle",
        ),
        family(
            "fashion-nike-air-max",
            "Nike Air Max Pulse",
            "Fashion",
            "Nike",
            "Sneakers",
            "Cushioned sneakers with sporty styling and easy everyday wear across multiple finishes.",
            "sneaker_red",
            [
                option("Black / Size 8", 129, default=True),
                option("White / Size 9", 129),
                option("Crimson / Size 10", 139),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-levis-501",
            "Levi's 501 Original Jeans",
            "Fashion",
            "Levi's",
            "Denim",
            "Timeless straight-fit denim that works for everyday styling and classic wardrobe builds.",
            "denim",
            [
                option("Indigo / 30W x 32L", 79, default=True),
                option("Stone Wash / 32W x 32L", 79),
                option("Black / 34W x 32L", 89),
            ],
            "Wash + Size",
        ),
        family(
            "fashion-adidas-ultraboost",
            "Adidas Ultraboost 23",
            "Fashion",
            "Adidas",
            "Running Style",
            "Comfort-focused runners that bridge performance and streetwear with an energetic silhouette.",
            "sneaker_red",
            [
                option("Core Black / Size 8", 169, default=True),
                option("Cloud White / Size 9", 179),
                option("Pulse Olive / Size 10", 179),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-zara-structured-coat",
            "Zara Structured Wool Coat",
            "Fashion",
            "Zara",
            "Outerwear",
            "Sharp tailored outerwear that instantly makes the storefront feel more premium and seasonal.",
            "coat",
            [
                option("Camel / Medium", 149, default=True),
                option("Graphite / Large", 159),
                option("Stone / XL", 159),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-nike-hoodie",
            "Nike Sportswear Hoodie",
            "Fashion",
            "Nike",
            "Casualwear",
            "Soft everyday hoodie with a clean athletic look for relaxed casual styling and layering.",
            "hoodie",
            [
                option("Black / Medium", 69, default=True),
                option("Heather Gray / Large", 69),
                option("Clay Beige / XL", 75),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-luxe-handbag",
            "Astra Luxe Handbag",
            "Fashion",
            "Astra",
            "Handbags",
            "Polished shoulder bag with premium hardware and statement finishes for fashion-first shoppers.",
            "handbag",
            [
                option("Black Mini", 119, default=True),
                option("Sand Medium", 139),
                option("Burgundy Large", 149),
            ],
            "Size + Finish",
        ),
        family(
            "home-instant-pot",
            "Instant Pot Duo",
            "Home & Kitchen",
            "Instant Pot",
            "Cookers",
            "Countertop multi-cooker that makes the home catalog feel practical, complete, and family ready.",
            "kitchen",
            [
                option("6 Quart", 99, default=True),
                option("8 Quart", 129),
            ],
            "Capacity",
        ),
        family(
            "home-kitchenaid-mixer",
            "KitchenAid Artisan Stand Mixer",
            "Home & Kitchen",
            "KitchenAid",
            "Appliances",
            "Iconic countertop mixer with stylish finishes that doubles as a premium kitchen centerpiece.",
            "mixer",
            [
                option("Almond Cream / 5 Quart", 479, default=True),
                option("Matte Black / 5 Quart", 499),
            ],
            "Finish + Capacity",
        ),
        family(
            "home-breville-espresso",
            "Breville Barista Touch",
            "Home & Kitchen",
            "Breville",
            "Coffee",
            "Touchscreen espresso machine for a cafe-style coffee setup with a polished premium feel.",
            "coffee",
            [
                option("Brushed Stainless", 799, default=True),
                option("Black Truffle", 829),
            ],
            "Finish",
        ),
        family(
            "home-dyson-vacuum",
            "Dyson V15 Detect",
            "Home & Kitchen",
            "Dyson",
            "Cleaning",
            "High-powered cordless vacuum with smart cleaning heads and a premium tech-forward finish.",
            "vacuum",
            [
                option("Absolute", 699, default=True),
                option("Complete", 799),
            ],
            "Bundle",
        ),
        family(
            "home-ninja-air-fryer",
            "Ninja Air Fryer",
            "Home & Kitchen",
            "Ninja",
            "Appliances",
            "Compact air fryer lineup that adds accessible, everyday kitchen upgrades to the catalog.",
            "kitchen",
            [
                option("4 Quart", 129, default=True),
                option("FlexDrawer XL", 189),
            ],
            "Size",
        ),
        family(
            "beauty-ordinary-serum",
            "The Ordinary Hyaluronic Acid",
            "Beauty & Personal Care",
            "The Ordinary",
            "Skincare",
            "Daily hydration serum that brings an affordable skincare story into the beauty aisle.",
            "serum",
            [
                option("30 ml", 9, default=True),
                option("60 ml", 15),
                option("Starter Routine", 21),
            ],
            "Size",
        ),
        family(
            "beauty-dyson-airwrap",
            "Dyson Airwrap Multi-Styler",
            "Beauty & Personal Care",
            "Dyson",
            "Hair Styling",
            "Premium hair styling system with gift-worthy finishes and a standout aspirational look.",
            "beauty_tools",
            [
                option("Copper / Long Barrel", 599, default=True),
                option("Ceramic Pink", 599),
                option("Blue / Multi-Styler Complete", 649),
            ],
            "Finish",
        ),
        family(
            "beauty-cerave-moisturizer",
            "CeraVe Moisturizing Cream",
            "Beauty & Personal Care",
            "CeraVe",
            "Skincare",
            "Barrier-supporting moisturizer that rounds out the beauty catalog with trusted daily essentials.",
            "serum",
            [
                option("340 g", 16, default=True),
                option("539 g", 22),
                option("Family Bundle", 29),
            ],
            "Size",
        ),
        family(
            "beauty-luxury-fragrance",
            "Maison Lumiere Eau de Parfum",
            "Beauty & Personal Care",
            "Maison Lumiere",
            "Fragrance",
            "Luxury fragrance line with layered notes and elegant packaging built for a richer storefront.",
            "fragrance",
            [
                option("50 ml", 72, default=True),
                option("100 ml", 98),
                option("Gift Set", 119),
            ],
            "Size",
        ),
        family(
            "sport-nike-pegasus",
            "Nike Air Zoom Pegasus 40",
            "Sports & Fitness",
            "Nike",
            "Running",
            "Reliable running shoe with responsive cushioning for walkers, runners, and active daily routines.",
            "sneaker_red",
            [
                option("Black / Size 8", 129, default=True),
                option("Blue / Size 9", 129),
                option("White / Size 10", 139),
            ],
            "Finish + Size",
        ),
        family(
            "sport-fitbit-charge",
            "Fitbit Charge 6",
            "Sports & Fitness",
            "Fitbit",
            "Wearables",
            "Fitness tracker with health metrics, Google features, and enough polish for an active lifestyle shelf.",
            "watch",
            [
                option("Obsidian Black", 149, default=True),
                option("Coral Gold", 149),
                option("Premium Bundle", 179),
            ],
            "Finish",
        ),
        family(
            "sport-peloton-bike",
            "Peloton Bike",
            "Sports & Fitness",
            "Peloton",
            "Exercise Equipment",
            "Connected indoor cycling setup for a high-ticket fitness feature in the storefront.",
            "bike",
            [
                option("Starter Package", 1449, default=True),
                option("Essentials Package", 1599),
                option("Bike+ Premium Package", 2249),
            ],
            "Bundle",
        ),
        family(
            "sport-manduka-yoga-mat",
            "Manduka Pro Yoga Mat",
            "Sports & Fitness",
            "Manduka",
            "Yoga",
            "Premium yoga mat with textured grip and lifestyle appeal for wellness-focused shoppers.",
            "yoga",
            [
                option("Black / 6 mm", 129, default=True),
                option("Sand / 6 mm", 129),
                option("Travel Set", 159),
            ],
            "Finish + Bundle",
        ),
        family(
            "book-atomic-habits",
            "Atomic Habits",
            "Books",
            "James Clear",
            "Personal Development",
            "A practical guide to habit building that gives the books section a highly recognizable bestseller anchor.",
            "books_stack",
            [option("Paperback", 16, default=True)],
        ),
        family(
            "book-psychology-of-money",
            "The Psychology of Money",
            "Books",
            "Morgan Housel",
            "Finance",
            "Clear lessons on money behavior and decision-making for readers who enjoy practical non-fiction.",
            "books_open",
            [option("Paperback", 15, default=True)],
        ),
        family(
            "book-sapiens",
            "Sapiens",
            "Books",
            "Yuval Noah Harari",
            "History",
            "A sweeping history title that gives the catalog depth beyond pure tech and lifestyle shopping.",
            "books_stack",
            [option("Paperback", 18, default=True)],
        ),
        family(
            "book-midnight-library",
            "The Midnight Library",
            "Books",
            "Matt Haig",
            "Fiction",
            "A contemporary fiction favorite that adds warmth and variety to the books lane.",
            "books_open",
            [option("Paperback", 13, default=True)],
        ),
        family(
            "book-dune",
            "Dune",
            "Books",
            "Frank Herbert",
            "Science Fiction",
            "Epic science fiction classic that strengthens the catalog with recognizable genre depth.",
            "books_stack",
            [option("Mass Market", 12, default=True)],
        ),
        family(
            "book-becoming",
            "Becoming",
            "Books",
            "Michelle Obama",
            "Memoir",
            "Bestselling memoir that rounds out the book section with biography and inspirational reading.",
            "books_open",
            [option("Paperback", 17, default=True)],
        ),
        family(
            "toy-lego-creative-build",
            "LEGO Creator Cosmic Build",
            "Toys & Games",
            "LEGO",
            "Building Sets",
            "Creative building set for younger shoppers, collectors, and parents looking for display-ready fun.",
            "lego",
            [
                option("Starter Box", 59, default=True),
                option("Mega Build Box", 99),
            ],
            "Set Size",
        ),
        family(
            "toy-boardgame-night",
            "Codenames Party Edition",
            "Toys & Games",
            "Czech Games",
            "Board Games",
            "Fast team-based word game that gives the catalog a recognizable party-night option.",
            "boardgame",
            [
                option("Classic Box", 19, default=True),
                option("Party Pack", 29),
            ],
            "Edition",
        ),
        family(
            "toy-remote-racer",
            "Turbo RC Drift Racer",
            "Toys & Games",
            "Turbo",
            "RC Toys",
            "Remote-control racer with a giftable price point and stronger toy shelf variety.",
            "lego",
            [
                option("Single Battery", 69, default=True),
                option("Dual Battery Pack", 89),
            ],
            "Bundle",
        ),
        family(
            "toy-puzzle-master",
            "Ravensburger World Puzzle",
            "Toys & Games",
            "Ravensburger",
            "Puzzles",
            "Detailed puzzle range that adds family-friendly tabletop variety and slower-play options.",
            "boardgame",
            [
                option("1000 Pieces", 24, default=True),
                option("2000 Pieces", 36),
            ],
            "Piece Count",
        ),
        family(
            "toy-console-fun",
            "Nintendo Switch Sports Party",
            "Toys & Games",
            "Nintendo",
            "Party Games",
            "Group-friendly game bundle that helps the toys section feel broader than just kids-only products.",
            "console",
            [
                option("Game Card", 49, default=True),
                option("Party Bundle", 69),
            ],
            "Bundle",
        ),
    ] + build_expansion_families()


def build_expansion_families():
    return [
        family(
            "mobile-motorola-edge-50-ultra",
            "Motorola Edge 50 Ultra",
            "Mobiles",
            "Motorola",
            "Smartphones",
            "Slim premium Android phone with fast charging, polished materials, and a camera-first daily experience.",
            "",
            [
                option("256GB / Forest Grey", 899, default=True),
                option("512GB / Peach Fuzz", 999),
                option("512GB / Nordic Wood", 1019),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-asus-rog-phone-8-pro",
            "Asus ROG Phone 8 Pro",
            "Mobiles",
            "Asus",
            "Gaming Phones",
            "Gaming-focused flagship with high refresh visuals, shoulder controls, and a powerful cooling-ready design.",
            "",
            [
                option("256GB / Phantom Black", 999, default=True),
                option("512GB / Storm Gray", 1149),
                option("1TB / Pro Vision Edition", 1399),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-vivo-x100-pro",
            "Vivo X100 Pro",
            "Mobiles",
            "Vivo",
            "Smartphones",
            "Flagship camera phone with a bold portrait system, polished curves, and premium everyday performance.",
            "",
            [
                option("256GB / Asteroid Black", 949, default=True),
                option("512GB / Sunset Orange", 1049),
                option("512GB / Glacier Blue", 1049),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-oppo-find-x7-ultra",
            "Oppo Find X7 Ultra",
            "Mobiles",
            "Oppo",
            "Smartphones",
            "Luxury Android flagship with Hasselblad styling, sharp imaging, and a premium curved display.",
            "",
            [
                option("256GB / Ocean Black", 999, default=True),
                option("512GB / Sepia Brown", 1129),
                option("1TB / Ceramic White", 1349),
            ],
            "Storage + Finish",
        ),
        family(
            "mobile-honor-magic6-pro",
            "Honor Magic6 Pro",
            "Mobiles",
            "Honor",
            "Smartphones",
            "Large-screen flagship with standout battery life, bright visuals, and polished flagship finishing.",
            "",
            [
                option("256GB / Epi Green", 899, default=True),
                option("512GB / Black", 999),
                option("512GB / Cloud Purple", 1019),
            ],
            "Storage + Finish",
        ),
        family(
            "electronics-lenovo-yoga-9i",
            "Lenovo Yoga 9i",
            "Electronics",
            "Lenovo",
            "Laptops",
            "Convertible premium laptop with a rotating soundbar hinge and polished creator-friendly design.",
            "",
            [
                option("14-inch / 16GB / 512GB / Storm Grey", 1399, default=True),
                option("14-inch / 16GB / 1TB / Oatmeal", 1599),
                option("OLED / 32GB / 1TB / Cosmic Blue", 1849),
            ],
            "Config + Finish",
        ),
        family(
            "electronics-hp-spectre-x360-14",
            "HP Spectre x360 14",
            "Electronics",
            "HP",
            "Laptops",
            "Premium 2-in-1 laptop with gem-cut accents, strong battery life, and a presentation-ready finish.",
            "",
            [
                option("16GB / 512GB / Nightfall Black", 1349, default=True),
                option("16GB / 1TB / Slate Blue", 1499),
                option("OLED / 32GB / 1TB / Silver", 1799),
            ],
            "Config + Finish",
        ),
        family(
            "electronics-bose-qc-ultra",
            "Bose QuietComfort Ultra",
            "Electronics",
            "Bose",
            "Headphones",
            "Flagship over-ear headphones with immersive audio and a refined premium-travel look.",
            "",
            [
                option("Black", 429, default=True),
                option("White Smoke", 429),
                option("Sandstone", 449),
            ],
            "Finish",
        ),
        family(
            "electronics-samsung-tab-s9-plus",
            "Samsung Galaxy Tab S9 Plus",
            "Electronics",
            "Samsung",
            "Tablets",
            "Water-resistant Android tablet with S Pen productivity and a bold entertainment-first display.",
            "",
            [
                option("256GB / Graphite", 999, default=True),
                option("512GB / Beige", 1119),
                option("Creator Bundle / Graphite", 1199),
            ],
            "Storage + Finish",
        ),
        family(
            "electronics-gopro-hero12",
            "GoPro HERO12 Black",
            "Electronics",
            "GoPro",
            "Action Cameras",
            "Adventure camera with stabilization, durable portability, and creator bundles for outdoor content.",
            "",
            [
                option("Camera Only", 399, default=True),
                option("Creator Edition", 549),
                option("Adventure Kit", 589),
            ],
            "Bundle",
        ),
        family(
            "fashion-uniqlo-ultra-light-down",
            "Uniqlo Ultra Light Down Jacket",
            "Fashion",
            "Uniqlo",
            "Outerwear",
            "Lightweight insulated jacket that layers easily and gives the fashion aisle a polished everyday staple.",
            "",
            [
                option("Black / Medium", 89, default=True),
                option("Olive / Large", 89),
                option("Navy / XL", 95),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-puma-rsx-heritage",
            "Puma RS-X Heritage",
            "Fashion",
            "Puma",
            "Sneakers",
            "Chunky lifestyle sneaker with color-block styling and a more playful streetwear profile.",
            "",
            [
                option("White / Size 8", 119, default=True),
                option("Black / Size 9", 119),
                option("Teal / Size 10", 129),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-rayban-wayfarer",
            "Ray-Ban Original Wayfarer",
            "Fashion",
            "Ray-Ban",
            "Accessories",
            "Classic premium sunglasses that instantly make the accessory shelf feel more complete.",
            "",
            [
                option("Black / Green Lens", 169, default=True),
                option("Tortoise / Brown Lens", 179),
                option("Matte Black / Polarized", 209),
            ],
            "Frame + Lens",
        ),
        family(
            "fashion-mango-satin-midi-dress",
            "Mango Satin Midi Dress",
            "Fashion",
            "Mango",
            "Dresses",
            "Elegant occasion-ready dress with a clean silhouette and polished color options.",
            "",
            [
                option("Emerald / Small", 99, default=True),
                option("Champagne / Medium", 109),
                option("Black / Large", 109),
            ],
            "Finish + Size",
        ),
        family(
            "fashion-coach-willow-tote",
            "Coach Willow Tote",
            "Fashion",
            "Coach",
            "Handbags",
            "Structured tote bag with premium hardware and gift-ready finishes for an elevated accessory story.",
            "",
            [
                option("Canvas / Chalk", 249, default=True),
                option("Pebble Leather / Black", 299),
                option("Colorblock / Sand", 319),
            ],
            "Finish",
        ),
        family(
            "home-philips-air-fryer-xxl",
            "Philips Air Fryer XXL",
            "Home & Kitchen",
            "Philips",
            "Appliances",
            "Large-capacity air fryer built for premium countertop presentation and family-size convenience.",
            "",
            [
                option("Standard Basket", 239, default=True),
                option("Smart Sensing", 289),
                option("Premium Accessory Bundle", 329),
            ],
            "Bundle",
        ),
        family(
            "home-delonghi-dinamica",
            "DeLonghi Dinamica LatteCrema",
            "Home & Kitchen",
            "DeLonghi",
            "Coffee",
            "Automatic espresso system with cafe-style milk drinks and a polished luxury-kitchen appeal.",
            "",
            [
                option("Silver", 899, default=True),
                option("Titanium", 949),
                option("Latte Bundle", 999),
            ],
            "Finish",
        ),
        family(
            "home-nespresso-vertuo-next",
            "Nespresso Vertuo Next",
            "Home & Kitchen",
            "Nespresso",
            "Coffee",
            "Compact pod coffee system that helps the catalog feel practical, modern, and easy to demo.",
            "",
            [
                option("Matte Black", 179, default=True),
                option("Light Gray", 179),
                option("Welcome Bundle", 219),
            ],
            "Finish + Bundle",
        ),
        family(
            "home-vitamix-e310",
            "Vitamix Explorian E310",
            "Home & Kitchen",
            "Vitamix",
            "Appliances",
            "Premium blender with serious power and a professional countertop look for kitchen enthusiasts.",
            "",
            [
                option("Black", 349, default=True),
                option("Red", 369),
                option("Starter Smoothie Kit", 399),
            ],
            "Finish",
        ),
        family(
            "home-cuisinart-food-processor",
            "Cuisinart 14-Cup Food Processor",
            "Home & Kitchen",
            "Cuisinart",
            "Appliances",
            "Large-capacity processor that adds practical prep gear and strong everyday value to the home aisle.",
            "",
            [
                option("White", 219, default=True),
                option("Brushed Chrome", 239),
                option("Chef Bundle", 269),
            ],
            "Finish + Bundle",
        ),
        family(
            "book-deep-work",
            "Deep Work",
            "Books",
            "Cal Newport",
            "Productivity",
            "Focused productivity title that fits naturally into a polished books and learning section.",
            "",
            [
                option("Paperback", 14, default=True),
                option("Hardcover", 22),
                option("Collector Edition", 29),
            ],
            "Edition",
        ),
        family(
            "book-the-alchemist",
            "The Alchemist",
            "Books",
            "Paulo Coelho",
            "Fiction",
            "Timeless inspirational fiction pick that makes the books aisle feel broader and more recognizable.",
            "",
            [
                option("Paperback", 13, default=True),
                option("Hardcover", 21),
                option("Illustrated Edition", 28),
            ],
            "Edition",
        ),
        family(
            "book-rich-dad-poor-dad",
            "Rich Dad Poor Dad",
            "Books",
            "Robert T. Kiyosaki",
            "Finance",
            "Popular finance title that strengthens the practical learning side of the catalog.",
            "",
            [
                option("Paperback", 12, default=True),
                option("Hardcover", 20),
                option("Anniversary Edition", 26),
            ],
            "Edition",
        ),
        family(
            "book-ikigai",
            "Ikigai",
            "Books",
            "Hector Garcia",
            "Lifestyle",
            "Wellness and purpose bestseller that adds softer lifestyle reading to the storefront.",
            "",
            [
                option("Paperback", 15, default=True),
                option("Hardcover", 23),
                option("Gift Edition", 29),
            ],
            "Edition",
        ),
        family(
            "book-project-hail-mary",
            "Project Hail Mary",
            "Books",
            "Andy Weir",
            "Science Fiction",
            "High-energy modern science fiction bestseller that expands the books lane with a popular recent hit.",
            "",
            [
                option("Paperback", 16, default=True),
                option("Hardcover", 25),
                option("Collector Edition", 32),
            ],
            "Edition",
        ),
        family(
            "sport-garmin-forerunner-265",
            "Garmin Forerunner 265",
            "Sports & Fitness",
            "Garmin",
            "Wearables",
            "Training-focused GPS watch with a bright display and polished performance metrics for runners.",
            "",
            [
                option("Black / 42 mm", 449, default=True),
                option("Aqua / 42 mm", 449),
                option("Whitestone / 46 mm", 479),
            ],
            "Finish + Size",
        ),
        family(
            "sport-apple-watch-se",
            "Apple Watch SE",
            "Sports & Fitness",
            "Apple",
            "Wearables",
            "Accessible smartwatch that blends fitness tracking, daily notifications, and a familiar premium finish.",
            "",
            [
                option("40 mm / Midnight", 249, default=True),
                option("44 mm / Starlight", 279),
                option("44 mm / Sport Loop Bundle", 309),
            ],
            "Size + Finish",
        ),
        family(
            "sport-bowflex-selecttech-552",
            "Bowflex SelectTech 552",
            "Sports & Fitness",
            "Bowflex",
            "Strength Training",
            "Adjustable dumbbell set that helps the fitness aisle feel complete for home training demos.",
            "",
            [
                option("Single Dumbbell", 229, default=True),
                option("Pair Set", 429),
                option("Pair + Bench Bundle", 599),
            ],
            "Bundle",
        ),
        family(
            "sport-theragun-prime",
            "Theragun Prime",
            "Sports & Fitness",
            "Therabody",
            "Recovery",
            "Premium recovery gun that gives the sports section a strong wellness and post-workout angle.",
            "",
            [
                option("Black", 299, default=True),
                option("White", 299),
                option("Recovery Kit Bundle", 349),
            ],
            "Finish",
        ),
        family(
            "sport-hydro-flask-trail-bottle",
            "Hydro Flask Trail Bottle",
            "Sports & Fitness",
            "Hydro Flask",
            "Outdoor Gear",
            "Lightweight insulated bottle that rounds out the fitness catalog with active everyday essentials.",
            "",
            [
                option("24 oz / Black", 39, default=True),
                option("32 oz / Pacific", 45),
                option("Trail Bundle", 59),
            ],
            "Size + Finish",
        ),
        family(
            "beauty-laneige-sleeping-mask",
            "Laneige Water Sleeping Mask",
            "Beauty & Personal Care",
            "Laneige",
            "Skincare",
            "Overnight hydration favorite that adds a recognizable K-beauty product to the beauty cabinet.",
            "",
            [
                option("25 ml", 18, default=True),
                option("70 ml", 34),
                option("Gift Duo", 49),
            ],
            "Size",
        ),
        family(
            "beauty-clinique-moisture-surge",
            "Clinique Moisture Surge",
            "Beauty & Personal Care",
            "Clinique",
            "Skincare",
            "Gel-cream moisturizer with a clean premium feel and broad everyday appeal.",
            "",
            [
                option("30 ml", 19, default=True),
                option("50 ml", 32),
                option("100 ml", 49),
            ],
            "Size",
        ),
        family(
            "beauty-olaplex-no3",
            "Olaplex No. 3 Hair Perfector",
            "Beauty & Personal Care",
            "Olaplex",
            "Hair Care",
            "Bond-building hair treatment that adds salon-style care to the beauty and self-care shelf.",
            "",
            [
                option("100 ml", 30, default=True),
                option("250 ml", 54),
                option("Repair Duo", 68),
            ],
            "Size",
        ),
        family(
            "beauty-charlotte-tilbury-pillow-talk",
            "Charlotte Tilbury Pillow Talk Kit",
            "Beauty & Personal Care",
            "Charlotte Tilbury",
            "Makeup",
            "Giftable makeup set with polished packaging and a premium editorial look.",
            "",
            [
                option("Lip Kit", 45, default=True),
                option("Face Kit", 65),
                option("Icon Bundle", 89),
            ],
            "Set Type",
        ),
        family(
            "beauty-rare-beauty-soft-pinch",
            "Rare Beauty Soft Pinch Blush",
            "Beauty & Personal Care",
            "Rare Beauty",
            "Makeup",
            "Viral liquid blush with bright color stories and a modern beauty-shelf presence.",
            "",
            [
                option("Hope", 24, default=True),
                option("Joy", 24),
                option("Blush Trio", 59),
            ],
            "Shade",
        ),
        family(
            "toy-hot-wheels-track-builder",
            "Hot Wheels Track Builder",
            "Toys & Games",
            "Hot Wheels",
            "RC Toys",
            "Bright stunt track set that boosts the toy aisle with fast, gift-friendly action play.",
            "",
            [
                option("Starter Loop Set", 34, default=True),
                option("Turbo Builder Set", 49),
                option("Ultimate Stunt Bundle", 69),
            ],
            "Set Size",
        ),
        family(
            "toy-monopoly-deluxe",
            "Monopoly Deluxe Edition",
            "Toys & Games",
            "Hasbro",
            "Board Games",
            "Premium family board game edition that adds a recognizable tabletop classic to the catalog.",
            "",
            [
                option("Classic Deluxe", 39, default=True),
                option("Wood Storage Edition", 59),
                option("Family Night Bundle", 74),
            ],
            "Edition",
        ),
        family(
            "toy-nerf-elite-commander",
            "Nerf Elite 2.0 Commander",
            "Toys & Games",
            "Nerf",
            "Action Toys",
            "Blaster play set that makes the toy selection feel broader, more playful, and more energetic.",
            "",
            [
                option("Blaster Only", 24, default=True),
                option("Target Kit", 34),
                option("Battle Pack", 49),
            ],
            "Bundle",
        ),
        family(
            "toy-barbie-dream-closet",
            "Barbie Dream Closet",
            "Toys & Games",
            "Barbie",
            "Dolls & Playsets",
            "Colorful fashion playset that gives the toy aisle a stronger lifestyle and gifting presence.",
            "",
            [
                option("Closet Set", 49, default=True),
                option("Closet + Doll Bundle", 64),
                option("Ultimate Fashion Set", 89),
            ],
            "Bundle",
        ),
        family(
            "toy-jenga-giant-party",
            "Jenga Giant Party Set",
            "Toys & Games",
            "Jenga",
            "Party Games",
            "Oversized stacking game that adds event-ready fun and more variety to the social games section.",
            "",
            [
                option("Classic Giant", 79, default=True),
                option("Outdoor Edition", 99),
                option("Party Bundle", 119),
            ],
            "Edition",
        ),
    ]


def create_products():
    families = build_families()
    seen_thumb_urls = set()
    for family_row in families:
        thumb_url = family_row["images"]["thumb"]
        if thumb_url in seen_thumb_urls:
            family_row["images"] = name_based_image(
                family_row["family_id"],
                family_row["name"],
                family_row["brand"],
                family_row["category"],
                family_row["subcategory"],
            )
        seen_thumb_urls.add(family_row["images"]["thumb"])

    # Load fix.txt mappings to apply them directly into the dataset
    fix_path = os.path.join(DATA_DIR, "..", "..", "fix.txt")
    fix_mappings = {}
    if os.path.exists(fix_path):
        with open(fix_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                name, url = line.split(":", 1)
                normalized_name = re.sub(r"\s+", " ", name.strip().lower())
                fix_mappings[normalized_name] = url.strip()

    rows = []
    product_id = 1

    for family_row in families:
        for variant in family_row["variants"]:
            base_name = family_row["name"]
            variant_label = variant["label"]
            full_name = f"{base_name} - {variant_label}" if variant_label else base_name
            
            normalized_base = re.sub(r"\s+", " ", base_name.strip().lower())
            normalized_full = re.sub(r"\s+", " ", full_name.strip().lower())
            
            thumb_url = fix_mappings.get(normalized_full) or fix_mappings.get(normalized_base) or family_row["images"]["thumb"]
            hero_url = fix_mappings.get(normalized_full) or fix_mappings.get(normalized_base) or family_row["images"]["hero"]

            row = {
                "product_id": product_id,
                "product_family_id": family_row["family_id"],
                "name": family_row["name"],
                "brand": family_row["brand"],
                "category": family_row["category"],
                "subcategory": family_row["subcategory"],
                "description": family_row["description"],
                "price": round(variant["price"], 2),
                "variant_type": family_row["variant_type"],
                "variant_value": variant["value"],
                "variant_label": variant["label"],
                "is_default": "true" if variant.get("default") else "false",
                "thumb_image_url": thumb_url,
                "hero_image_url": hero_url,
                "image_url": thumb_url,
            }
            rows.append(row)
            product_id += 1

    if len(rows) < 220:
        raise ValueError(f"Expected at least 220 product rows, generated {len(rows)}")

    fieldnames = [
        "product_id",
        "product_family_id",
        "name",
        "brand",
        "category",
        "subcategory",
        "description",
        "price",
        "variant_type",
        "variant_value",
        "variant_label",
        "is_default",
        "thumb_image_url",
        "hero_image_url",
        "image_url",
    ]

    with open(PRODUCTS_FILE, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} products to {PRODUCTS_FILE}")


def create_interactions(num_users=320, num_events=None, seed=42):
    random.seed(seed)
    now = datetime.utcnow()

    with open(PRODUCTS_FILE, newline="", encoding="utf-8") as file_obj:
        rows = list(csv.DictReader(file_obj))

    product_ids = [int(row["product_id"]) for row in rows]
    family_map = {}
    for row in rows:
        family_map.setdefault(row["product_family_id"], []).append(int(row["product_id"]))

    if num_events is None:
        num_events = max(7200, len(product_ids) * 45)

    popularity = [1.0 + (len(product_ids) - index) * 0.008 for index, _ in enumerate(product_ids)]
    total_weight = sum(popularity)
    weights = [value / total_weight for value in popularity]

    with open(INTERACTIONS_FILE, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=["user_id", "product_id", "quantity", "timestamp"],
        )
        writer.writeheader()

        for _ in range(num_events):
            user_id = random.randint(1, num_users)
            chosen_product = random.choices(product_ids, weights)[0]

            if random.random() < 0.22:
                family_id = next(
                    row["product_family_id"]
                    for row in rows
                    if int(row["product_id"]) == chosen_product
                )
                chosen_product = random.choice(family_map[family_id])

            quantity = 1 if random.random() < 0.84 else random.randint(1, 3)
            timestamp = now - timedelta(seconds=random.randint(0, 60 * 60 * 24 * 35))
            writer.writerow(
                {
                    "user_id": user_id,
                    "product_id": chosen_product,
                    "quantity": quantity,
                    "timestamp": timestamp.isoformat(),
                }
            )

    print(f"Wrote interactions ({num_events}) to {INTERACTIONS_FILE}")


if __name__ == "__main__":
    create_products()
    create_interactions()
