#!/usr/bin/env python3
"""
sync_ozparts.py — автоматизиран pipeline за autofixparts24.com
=================================================================

Какво прави:
    1. Дърпа datapack (5 бранда), stocklist и applications от 3cerp.eu API.
    2. Обединява ги по SKU.
    3. Прилага търговски марж върху RRP.
    4. Изчислява обща наличност (NL + PL + Manufacturer).
    5. Генерира два output файла:
        - cloudcart_feed.xml  — за импорт в CloudCart
        - vehicle_index.json  — за Vehicle Filter widget на сайта
    6. Качва ги на CDN (S3 / Cloudflare R2 / GitHub raw / static host).

Деплой:
    - Render.com Cron Job (free tier, schedule: "0 */6 * * *")
    - GitHub Actions (.github/workflows/sync.yml, cron: every 6h)
    - VPS + crontab (`0 */6 * * * /usr/bin/python3 /opt/sync_ozparts.py`)

Зависимости:
    pip install requests boto3   # boto3 само ако ползваш S3 / R2

Конфигурация (environment variables):
    OZPARTS_PROJECT     — твоят `p` параметър (примерно: 5e1eb95286eb633860334f64)
    OZPARTS_USER        — твоят `u` параметър (примерно: 6356b4b0343bd836f5079a29)
    DATAPACK_URLS       — JSON: { "Pedders": "https://...", "Hawk": "https://..." }
    UPLOAD_DEST         — "local" | "s3" | "r2" | "github"
    S3_BUCKET, S3_KEY_ID, S3_KEY_SECRET (ако UPLOAD_DEST=s3 или r2)
    GITHUB_REPO, GITHUB_TOKEN  (ако UPLOAD_DEST=github)

    MARGIN_PCT          — % марж върху доставната цена (default 30)
    SUPPLIER_DISCOUNT   — % отстъпка от RRP за теб (default 20)
    VAT_PCT             — % ДДС (default 20 за България)
    PRICE_ROUND         — psychological rounding: "0.95" | "0.90" | "" (default "0.95")
"""

from __future__ import annotations
import os, sys, json, csv, re, io, gzip, time
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

PROJECT = os.environ.get("OZPARTS_PROJECT", "5e1eb95286eb633860334f64")
USER    = os.environ.get("OZPARTS_USER",    "6356b4b0343bd836f5079a29")

# Data pack URLs per brand. Тук слагаш всички 5 бранда.
DATAPACK_URLS = json.loads(os.environ.get("DATAPACK_URLS", json.dumps({
    "Pedders":      "https://ozparts2.usermd.net/API%20-%20Pedders%20data%20pack.json",
    # "Hawk":         "https://ozparts2.usermd.net/API%20-%20Hawk%20data%20pack.json",
    # "DBA":          "https://ozparts2.usermd.net/API%20-%20DBA%20data%20pack.json",
    # "ACL Race":     "https://ozparts2.usermd.net/API%20-%20ACL%20data%20pack.json",
    # "XtremeClutch": "https://ozparts2.usermd.net/API%20-%20XtremeClutch%20data%20pack.json",
})))

STOCKLIST_URL = f"https://3cerp.eu/api/stocklist/?p={PROJECT}&u={USER}&f=json"
APPLICATIONS_URL = f"https://3cerp.eu/api/applications/?p={PROJECT}&u={USER}&f=json"

MARGIN_PCT        = float(os.environ.get("MARGIN_PCT", "30"))           # печалба върху landed cost
SUPPLIER_DISCOUNT = float(os.environ.get("SUPPLIER_DISCOUNT", "20"))     # отстъпка от OzParts (RRP × 0.80 = твоят cost)
VAT_PCT           = float(os.environ.get("VAT_PCT", "20"))               # ДДС в България
PRICE_ROUND       = os.environ.get("PRICE_ROUND", "whole")               # "whole" | "0.95" | "0.99" | ""

# Транспортни разходи (OzParts → теб)
SHIPPING_PER_KG   = float(os.environ.get("SHIPPING_PER_KG", "2.00"))     # € на килограм — СМЕНИ КОГАТО ЗНАЕШ
SHIPPING_MIN      = float(os.environ.get("SHIPPING_MIN", "1.50"))        # минимум € на продукт
SHIPPING_FALLBACK = float(os.environ.get("SHIPPING_FALLBACK", "3.00"))   # ако няма weight

OUT_DIR = os.environ.get("OUT_DIR", "./out")
UPLOAD_DEST = os.environ.get("UPLOAD_DEST", "local")  # local | s3 | r2 | github

# ─────────────────────────────────────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> list | dict:
    print(f"  → GET {url[:80]}…")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.json()

def fetch_csv(url: str) -> list[dict]:
    print(f"  → GET {url[:80]}…")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    text = r.text
    if text.startswith("﻿"): text = text[1:]
    return list(csv.DictReader(io.StringIO(text)))

def fetch_all() -> tuple[dict, list, list]:
    """Returns (datapacks_by_brand, stocklist, applications)."""
    print("• Fetching datapacks…")
    datapacks = {}
    for brand, url in DATAPACK_URLS.items():
        try:
            datapacks[brand] = fetch_json(url)
            print(f"   {brand}: {len(datapacks[brand])} products")
        except Exception as e:
            print(f"   ⚠ {brand} failed: {e}")
            datapacks[brand] = []

    print("• Fetching stocklist…")
    # The JSON endpoint serves [object Object] garbage — use CSV instead.
    stock_url = STOCKLIST_URL.replace("f=json", "f=csv")
    stocklist = fetch_csv(stock_url)
    print(f"   {len(stocklist)} stock rows")

    print("• Fetching applications (fitment)…")
    applications = fetch_json(APPLICATIONS_URL)
    print(f"   {len(applications)} fitment rows")

    return datapacks, stocklist, applications

# ─────────────────────────────────────────────────────────────────────────────
# TRANSFORM
# ─────────────────────────────────────────────────────────────────────────────

def calc_shipping(weight_str: str) -> float:
    """Изчислява транспорт на брой по тегло."""
    try:
        kg = float(weight_str)
    except (TypeError, ValueError):
        return SHIPPING_FALLBACK
    if kg <= 0:
        return SHIPPING_FALLBACK
    return max(kg * SHIPPING_PER_KG, SHIPPING_MIN)

def calc_price(rrp_str: str, weight_str: str = "") -> tuple[float | None, dict]:
    """
    RRP → cost → +shipping → +margin → +VAT → round.
    Returns (final_price, breakdown_dict).
    """
    try:
        rrp = float(rrp_str)
    except (TypeError, ValueError):
        return None, {}
    cost = rrp * (1 - SUPPLIER_DISCOUNT / 100)         # твоят OzParts cost (без ДДС)
    shipping = calc_shipping(weight_str)               # транспорт на бройка
    landed_cost = cost + shipping                       # доставна с транспорт
    with_margin = landed_cost * (1 + MARGIN_PCT / 100) # +30% печалба
    with_vat = with_margin * (1 + VAT_PCT / 100)       # +20% ДДС
    # Закръгляне
    if PRICE_ROUND == "whole":
        final = float(int(with_vat) + 1)               # винаги нагоре до цял
    elif PRICE_ROUND in ("0.95", "0.99"):
        suffix = float(PRICE_ROUND)
        whole = int(with_vat)
        final = whole + suffix if with_vat - whole <= suffix else whole + 1 + suffix
    else:
        final = round(with_vat, 2)
    breakdown = {
        "rrp": round(rrp, 2),
        "cost": round(cost, 2),
        "shipping": round(shipping, 2),
        "landed": round(landed_cost, 2),
        "margin_amt": round(with_margin - landed_cost, 2),
        "vat_amt": round(with_vat - with_margin, 2),
        "final": round(final, 2),
        "profit_eur": round(with_margin - landed_cost, 2),
    }
    return round(final, 2), breakdown

def parse_year_range(s: str) -> tuple[int | None, int | None]:
    if not s: return (None, None)
    yrs = re.findall(r"(?:19|20)\d{2}", s)
    if len(yrs) >= 2: return (int(yrs[0]), int(yrs[1]))
    if len(yrs) == 1: return (int(yrs[0]), datetime.now().year + 1)
    return (None, None)

def build_unified(datapacks: dict, stocklist: list, applications: list) -> tuple[dict, dict]:
    """
    Returns:
        products  — { sku: {...all merged data...} }
        index     — { make: { model: [{variant, year_from, year_to, sku, group}] } }
    """
    # 1. Index stock by SKU
    stock_by_sku = {}
    for r in stocklist:
        sku = r.get("Item", "").strip()
        if not sku: continue
        nl = int(r.get("Available NL", "") or 0)
        pl = int(r.get("Available PL", "") or 0)
        mfr = int(r.get("Manufacturer Stock", "") or 0)
        stock_by_sku[sku] = {"nl": nl, "pl": pl, "mfr": mfr, "total": nl + pl + mfr}

    # 2. Merge products
    products = {}
    for brand, dp in datapacks.items():
        for p in dp:
            sku = p.get("Item", "").strip()
            if not sku: continue
            pics = [u.strip() for u in (p.get("Pictures", "") or "").split("|") if u.strip()]
            stock = stock_by_sku.get(sku, {"nl":0,"pl":0,"mfr":0,"total":0})
            products[sku] = {
                "sku": sku,
                "brand": p.get("Manufacturer", brand) or brand,
                "name": (p.get("Description") or "").strip(),
                "description_html": p.get("Detail Description", "") or "",
                "barcode": p.get("Barcode", "") or "",
                "weight": p.get("Weight", "") or "",
                "rrp": p.get("RRP", "") or "",
                "currency": p.get("Currency", "EUR"),
                "price": calc_price(p.get("RRP", ""), p.get("Weight", ""))[0],
                "pictures": pics,
                "stock": stock,
                "stock_total": stock["total"],
                "categories": [],   # filled below
                "groups": set(),
            }

    # Add fitment field to each product
    for p in products.values():
        p["fitment"] = {}  # {brand: set([model strings])}

    # 3. Index applications + back-fill categories AND fitment on products
    idx = {}
    for r in applications:
        item = r.get("item") or {}
        sku = (item.get("name") or "").strip()
        if not sku: continue
        cat = (item.get("categorydescription") or r.get("categorydescription") or "").strip()
        grp = (r.get("groupdescription") or "").strip()
        mk = (r.get("make") or "").strip()
        md = (r.get("model") or "").strip()
        var = (r.get("variant") or "").strip()
        yr_text = (r.get("year") or "").strip()

        if sku in products:
            if cat and cat not in products[sku]["categories"]:
                products[sku]["categories"].append(cat)
            if grp:
                products[sku]["groups"].add(grp)
            # Build fitment string per CloudCart's schema: "Variant (year_text)"
            if mk and md:
                model_label = md
                if var:
                    model_label += f" {var}"
                if yr_text:
                    # year_text идва като "316, E46 | 1999-Onward" — извличаме само годината
                    if "|" in yr_text:
                        model_label += f" ({yr_text.split('|')[-1].strip()})"
                    else:
                        # Понякога yr_text вече започва с вариант — ползваме само годинния range
                        import re as _re
                        m = _re.search(r"((?:19|20)\d{2}[-–](?:(?:19|20)\d{2}|Onward|Now))", yr_text)
                        if m: model_label += f" ({m.group(1)})"
                products[sku]["fitment"].setdefault(mk, set()).add(model_label)

        if mk and md:
            yf, yt = parse_year_range(yr_text)
            idx.setdefault(mk, {}).setdefault(md, []).append({
                "variant": var,
                "year_from": yf,
                "year_to": yt,
                "year_text": yr_text,
                "group": grp,
                "sku": sku,
            })

    # Convert sets to lists for JSON serialization
    for p in products.values():
        p["groups"] = sorted(p["groups"])
        p["fitment"] = {brand: sorted(models) for brand, models in p["fitment"].items()}

    return products, idx

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT — CloudCart product feed (XML)
# ─────────────────────────────────────────────────────────────────────────────

def write_cloudcart_feed(products: dict, path: str) -> None:
    """
    Generates a CloudCart-compatible product XML feed.
    Schema follows: https://cdncloudcart.com/storage/xml-structure-cloudcart.xml

    Field mapping (CloudCart side):
      - <id>                → Product Unique ID
      - <product_code>, <sku> → SKU (used for dedup via "Compare by")
      - <title>             → Product title
      - <description>       → HTML description
      - <category>          → Main category (from datapack)
      - <sub_category>      → Group (Front Shock, Rear Shock, etc.)
      - <manufacturer>      → Brand (Pedders, DBA, etc.)
      - <price>             → Final price WITH VAT (€, numeric)
      - <weight>            → kg
      - <quantity>          → Total stock across NL+PL+Manufacturer
      - <images><image>     → Multiple URLs
      - <category_properties> → Filterable properties (Group, NL stock, PL stock, …)
      - <brands><brand>     → Vehicle compatibility (Make + Models for Make/Model filter)
    """
    print(f"• Writing CloudCart feed → {path}")
    e = xml_escape
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<products>']
    skipped = 0

    for sku, p in products.items():
        if p["price"] is None:
            skipped += 1
            continue

        cats = p["categories"] or ["Авточасти"]
        category = cats[0] if cats else "Авточасти"
        sub_cat = p["groups"][0] if p["groups"] else ""

        images_xml = "".join(f"      <image>{e(u)}</image>\n" for u in p["pictures"][:8])

        # category_properties — допълнителни филтри по характеристики
        props = []
        if p["groups"]:
            vals = "".join(f"          <value><name>{e(g)}</name></value>\n" for g in p["groups"])
            props.append(f"""      <category_property name="Тип / Група">
        <values>
{vals}        </values>
      </category_property>""")
        # Stock locations като отделни properties
        if p["stock"]["nl"] > 0:
            props.append(f"""      <category_property name="Склад NL">
        <values><value><name>В наличност ({p["stock"]["nl"]} бр.)</name></value></values>
      </category_property>""")
        if p["stock"]["pl"] > 0:
            props.append(f"""      <category_property name="Склад PL">
        <values><value><name>В наличност ({p["stock"]["pl"]} бр.)</name></value></values>
      </category_property>""")
        category_props_xml = ""
        if props:
            category_props_xml = "    <category_properties>\n" + "\n".join(props) + "\n    </category_properties>\n"

        # brands — vehicle fitment (CloudCart native!)
        brands_xml = ""
        if p["fitment"]:
            brand_blocks = []
            for make_name, models in p["fitment"].items():
                model_xml = "".join(f"          <name>{e(m)}</name>\n" for m in models[:200])
                brand_blocks.append(f"""      <brand>
        <name>{e(make_name)}</name>
        <model>
{model_xml}        </model>
      </brand>""")
            brands_xml = "    <brands>\n" + "\n".join(brand_blocks) + "\n    </brands>\n"

        # Tags за SEO/search — комбинация от make + model + brand
        tag_set = [p["brand"]]
        for mk, models in p["fitment"].items():
            tag_set.append(mk)
            tag_set.extend(models[:5])
        tags = ", ".join(t for t in tag_set if t)[:500]

        lines.append(f"""  <product>
    <id>{e(sku)}</id>
    <product_code>{e(sku)}</product_code>
    <sku>{e(sku)}</sku>
    <barcode>{e(p["barcode"])}</barcode>
    <title>{e(p["name"])}</title>
    <description><![CDATA[{p["description_html"] or p["name"]}]]></description>
    <category>{e(category)}</category>
    <sub_category>{e(sub_cat)}</sub_category>
    <manufacturer>{e(p["brand"])}</manufacturer>
    <price>{p["price"]:.2f}</price>
    <old_price></old_price>
    <weight>{e(str(p["weight"]) if p["weight"] else "0")}</weight>
    <quantity>{p["stock_total"]}</quantity>
    <images>
{images_xml}    </images>
    <tags>{e(tags)}</tags>
    <meta_title>{e(p["name"][:70])}</meta_title>
    <meta_description>{e(p["name"][:160])}</meta_description>
{category_props_xml}{brands_xml}  </product>""")

    lines.append('</products>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"   {len(products) - skipped} products written, {skipped} skipped (no price)")

# ──────────�