#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_ozparts.py - automated pipeline for autofixparts24.com
Generates cloudcart_feed.xml and vehicle_index.json from OzParts API.
"""
from __future__ import annotations
import os, sys, json, csv, re, io, gzip, time
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
import requests
try:
    from translations import translate_category, translate_group, translate_name
except ImportError:
    def translate_category(s): return s
    def translate_group(s): return s
    def translate_name(s): return s

PROJECT = os.environ.get("OZPARTS_PROJECT", "5e1eb95286eb633860334f64")
USER    = os.environ.get("OZPARTS_USER",    "6356b4b0343bd836f5079a29")

DATAPACK_URLS = json.loads(os.environ.get("DATAPACK_URLS", json.dumps({
    "Pedders": "https://ozparts2.usermd.net/API%20-%20Pedders%20data%20pack.json",
})))

STOCKLIST_URL    = "https://3cerp.eu/api/stocklist/?p=" + PROJECT + "&u=" + USER + "&f=csv"
APPLICATIONS_URL = "https://3cerp.eu/api/applications/?p=" + PROJECT + "&u=" + USER + "&f=json"

MARGIN_PCT        = float(os.environ.get("MARGIN_PCT", "30"))
SUPPLIER_DISCOUNT = float(os.environ.get("SUPPLIER_DISCOUNT", "20"))
VAT_PCT           = float(os.environ.get("VAT_PCT", "20"))
PRICE_ROUND       = os.environ.get("PRICE_ROUND", "whole")
SHIPPING_PER_KG   = float(os.environ.get("SHIPPING_PER_KG", "2.00"))
SHIPPING_MIN      = float(os.environ.get("SHIPPING_MIN", "1.50"))
SHIPPING_FALLBACK = float(os.environ.get("SHIPPING_FALLBACK", "3.00"))
OUT_DIR     = os.environ.get("OUT_DIR", "./out")
UPLOAD_DEST = os.environ.get("UPLOAD_DEST", "local")


def fetch_json(url):
    print("  -> GET " + url[:100])
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.json()


def fetch_csv(url):
    print("  -> GET " + url[:100])
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    text = r.text
    if text and ord(text[0]) == 0xFEFF:
        text = text[1:]
    return list(csv.DictReader(io.StringIO(text)))


def fetch_all():
    print("* Fetching datapacks...")
    datapacks = {}
    for brand, url in DATAPACK_URLS.items():
        try:
            datapacks[brand] = fetch_json(url)
            print("   " + brand + ": " + str(len(datapacks[brand])) + " products")
        except Exception as e:
            print("   WARNING " + brand + " failed: " + str(e))
            datapacks[brand] = []
    print("* Fetching stocklist (csv)...")
    stocklist = fetch_csv(STOCKLIST_URL)
    print("   " + str(len(stocklist)) + " stock rows")
    print("* Fetching applications...")
    applications = fetch_json(APPLICATIONS_URL)
    print("   " + str(len(applications)) + " fitment rows")
    return datapacks, stocklist, applications


def calc_shipping(weight_str):
    try:
        kg = float(weight_str)
    except (TypeError, ValueError):
        return SHIPPING_FALLBACK
    if kg <= 0:
        return SHIPPING_FALLBACK
    return max(kg * SHIPPING_PER_KG, SHIPPING_MIN)


def calc_price(rrp_str, weight_str=""):
    try:
        rrp = float(rrp_str)
    except (TypeError, ValueError):
        return None, {}
    cost = rrp * (1 - SUPPLIER_DISCOUNT / 100)
    shipping = calc_shipping(weight_str)
    landed_cost = cost + shipping
    with_margin = landed_cost * (1 + MARGIN_PCT / 100)
    with_vat = with_margin * (1 + VAT_PCT / 100)
    if PRICE_ROUND == "whole":
        final = float(int(with_vat) + 1)
    elif PRICE_ROUND in ("0.95", "0.99"):
        suffix = float(PRICE_ROUND)
        whole = int(with_vat)
        final = whole + suffix if with_vat - whole <= suffix else whole + 1 + suffix
    else:
        final = round(with_vat, 2)
    return round(final, 2), {"rrp": round(rrp, 2), "final": round(final, 2)}


def parse_year_range(s):
    if not s:
        return (None, None)
    yrs = re.findall(r"(?:19|20)\d{2}", s)
    if len(yrs) >= 2:
        return (int(yrs[0]), int(yrs[1]))
    if len(yrs) == 1:
        return (int(yrs[0]), datetime.now().year + 1)
    return (None, None)


def build_unified(datapacks, stocklist, applications):
    stock_by_sku = {}
    for r in stocklist:
        sku = (r.get("Item", "") or "").strip()
        if not sku:
            continue
        try: nl = int(r.get("Available NL", "") or 0)
        except Exception: nl = 0
        try: pl = int(r.get("Available PL", "") or 0)
        except Exception: pl = 0
        try: mfr = int(r.get("Manufacturer Stock", "") or 0)
        except Exception: mfr = 0
        stock_by_sku[sku] = {"nl": nl, "pl": pl, "mfr": mfr, "total": nl + pl + mfr}

    products = {}
    for brand, dp in datapacks.items():
        for p in dp:
            sku = (p.get("Item", "") or "").strip()
            if not sku:
                continue
            pics = [u.strip() for u in (p.get("Pictures", "") or "").split("|") if u.strip()]
            stock = stock_by_sku.get(sku, {"nl": 0, "pl": 0, "mfr": 0, "total": 0})
            products[sku] = {
                "sku": sku,
                "brand": p.get("Manufacturer", brand) or brand,
                "name": translate_name((p.get("Description") or "").strip()),
                "description_html": p.get("Detail Description", "") or "",
                "barcode": p.get("Barcode", "") or "",
                "weight": p.get("Weight", "") or "",
                "rrp": p.get("RRP", "") or "",
                "currency": p.get("Currency", "EUR"),
                "price": calc_price(p.get("RRP", ""), p.get("Weight", ""))[0],
                "pictures": pics,
                "stock": stock,
                "stock_total": stock["total"],
                "categories": [],
                "groups": set(),
                "fitment": {},
            }

    idx = {}
    for r in applications:
        item = r.get("item") or {}
        sku = (item.get("name") or "").strip()
        if not sku:
            continue
        cat = (item.get("categorydescription") or r.get("categorydescription") or "").strip()
        grp = (r.get("groupdescription") or "").strip()
        mk = (r.get("make") or "").strip()
        md = (r.get("model") or "").strip()
        var = (r.get("variant") or "").strip()
        yr_text = (r.get("year") or "").strip()
        if sku in products:
            cat = translate_category(cat) if cat else cat
            if cat and cat not in products[sku]["categories"]:
                products[sku]["categories"].append(cat)
            if grp: grp = translate_group(grp)
            if grp:
                products[sku]["groups"].add(grp)
            if mk and md:
                model_label = md
                if var:
                    model_label += " " + var
                if yr_text:
                    if "|" in yr_text:
                        model_label += " (" + yr_text.split("|")[-1].strip() + ")"
                    else:
                        m = re.search(r"((?:19|20)\d{2}[-](?:(?:19|20)\d{2}|Onward|Now))", yr_text)
                        if m:
                            model_label += " (" + m.group(1) + ")"
                products[sku]["fitment"].setdefault(mk, set()).add(model_label)
        if mk and md:
            yf, yt = parse_year_range(yr_text)
            idx.setdefault(mk, {}).setdefault(md, []).append({
                "variant": var, "year_from": yf, "year_to": yt,
                "year_text": yr_text, "group": grp, "sku": sku,
            })

    for p in products.values():
        p["groups"] = sorted(p["groups"])
        p["fitment"] = {b: sorted(m) for b, m in p["fitment"].items()}
    return products, idx


def write_cloudcart_feed(products, path):
    print("* Writing CloudCart feed -> " + path)
    e = xml_escape
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<products>\n']
    skipped = 0
    for sku, p in products.items():
        if p["price"] is None:
            skipped += 1
            continue
        cats = p["categories"] or ["Uncategorized"]
        category = cats[0]
        sub_cat = p["groups"][0] if p["groups"] else ""
        images_xml = "".join("      <image>" + e(u) + "</image>\n" for u in p["pictures"][:8])
        props = []
        if p["groups"]:
            vals = "".join("          <value><name>" + e(g) + "</name></value>\n" for g in p["groups"])
            props.append('      <category_property name="Type / Group">\n        <values>\n' + vals + '        </values>\n      </category_property>')
        if p["stock"]["nl"] > 0:
            props.append('      <category_property name="Warehouse NL">\n        <values><value><name>In stock (' + str(p["stock"]["nl"]) + ')</name></value></values>\n      </category_property>')
        if p["stock"]["pl"] > 0:
            props.append('      <category_property name="Warehouse PL">\n        <values><value><name>In stock (' + str(p["stock"]["pl"]) + ')</name></value></values>\n      </category_property>')
        category_props_xml = ("    <category_properties>\n" + "\n".join(props) + "\n    </category_properties>\n") if props else ""
        brands_xml = ""
        if p["fitment"]:
            blocks = []
            for mk_name, models in p["fitment"].items():
                model_xml = "".join("          <name>" + e(m) + "</name>\n" for m in models[:200])
                blocks.append('      <brand>\n        <name>' + e(mk_name) + '</name>\n        <model>\n' + model_xml + '        </model>\n      </brand>')
            brands_xml = "    <brands>\n" + "\n".join(blocks) + "\n    </brands>\n"
        tag_set = [p["brand"]]
        for mk_name, models in p["fitment"].items():
            tag_set.append(mk_name)
            tag_set.extend(models[:5])
        tags = ", ".join(t for t in tag_set if t)[:500]
        weight_val = str(p["weight"]) if p["weight"] else "0"
        parts.append(
            "  <product>\n"
            "    <id>" + e(sku) + "</id>\n"
            "    <product_code>" + e(sku) + "</product_code>\n"
            "    <sku>" + e(sku) + "</sku>\n"
            "    <barcode>" + e(p["barcode"]) + "</barcode>\n"
            "    <title>" + e(p["name"]) + "</title>\n"
            "    <description><![CDATA[" + (p["description_html"] or p["name"]) + "]]></description>\n"
            "    <category>" + e(category) + "</category>\n"
            "    <sub_category>" + e(sub_cat) + "</sub_category>\n"
            "    <manufacturer>" + e(p["brand"]) + "</manufacturer>\n"
            "    <price>" + ("%.2f" % p["price"]) + "</price>\n"
            "    <old_price></old_price>\n"
            "    <weight>" + e(weight_val) + "</weight>\n"
            "    <quantity>" + str(p["stock_total"]) + "</quantity>\n"
            "    <images>\n" + images_xml + "    </images>\n"
            "    <tags>" + e(tags) + "</tags>\n"
            "    <meta_title>" + e(p["name"][:70]) + "</meta_title>\n"
            "    <meta_description>" + e(p["name"][:160]) + "</meta_description>\n"
            + category_props_xml + brands_xml +
            "  </product>\n"
        )
    parts.append("</products>\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print("   " + str(len(products) - skipped) + " products written, " + str(skipped) + " skipped")


def write_vehicle_index(idx, products, path):
    print("* Writing vehicle index -> " + path)
    product_lite = {}
    for sku, p in products.items():
        if p["price"] is None:
            continue
        product_lite[sku] = {
            "n": p["name"][:80],
            "p": p["price"],
            "i": p["pictures"][0] if p["pictures"] else "",
            "s": p["stock_total"],
            "b": p["brand"],
        }
    bundle = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "version": 1,
        "idx": idx,
        "products": product_lite,
    }
    raw = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    with gzip.open(path + ".gz", "wb") as gz:
        gz.write(raw.encode("utf-8"))
    print("   raw: " + str(len(raw) // 1024) + "KB, gz: " + str(os.path.getsize(path + ".gz") // 1024) + "KB")


def upload(path):
    if UPLOAD_DEST == "local":
        print("   (local mode - " + path + ")")


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=== sync_ozparts.py - " + datetime.utcnow().isoformat() + "Z ===")
    datapacks, stocklist, applications = fetch_all()
    products, idx = build_unified(datapacks, stocklist, applications)
    total_fitments = sum(len(v) for mk in idx.values() for v in mk.values())
    print("* Merged: " + str(len(products)) + " products, " + str(total_fitments) + " fitments")
    feed_path = os.path.join(OUT_DIR, "cloudcart_feed.xml")
    idx_path  = os.path.join(OUT_DIR, "vehicle_index.json")
    write_cloudcart_feed(products, feed_path)
    write_vehicle_index(idx, products, idx_path)
    upload(feed_path)
    upload(idx_path)
    upload(idx_path + ".gz")
    print("=== DONE in " + ("%.1f" % (time.time() - t0)) + "s ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
