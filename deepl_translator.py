# -*- coding: utf-8 -*-
"""
DeepL translator with persistent caching.
Uses header-based DeepL-Auth-Key authentication.
"""
from __future__ import annotations
import os
import json
import hashlib
import time

import requests


CACHE_PATH = os.environ.get("DEEPL_CACHE_PATH", "cache/translations.json")
CHAR_BUDGET_PER_RUN = int(os.environ.get("DEEPL_BUDGET_PER_RUN", "100000"))
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "")


def _api_base():
    if DEEPL_API_KEY.endswith(":fx"):
        return "https://api-free.deepl.com"
    return "https://api.deepl.com"


def _hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("WARNING: failed to load cache " + CACHE_PATH + ": " + str(e))
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


class Budget:
    def __init__(self, budget):
        self.budget = budget
        self.spent = 0
        self.exhausted = False

    def can_spend(self, n):
        return not self.exhausted and (self.spent + n) <= self.budget

    def spend(self, n):
        self.spent += n


def translate_html(html, cache, budget):
    if not html or not DEEPL_API_KEY:
        return html

    h = _hash(html)
    if h in cache:
        return cache[h]

    if not budget.can_spend(len(html)):
        return html

    try:
        r = requests.post(
            _api_base() + "/v2/translate",
            headers={"Authorization": "DeepL-Auth-Key " + DEEPL_API_KEY},
            data={
                "text": html,
                "target_lang": "BG",
                "source_lang": "EN",
                "tag_handling": "html",
                "preserve_formatting": "1",
            },
            timeout=60,
        )
        if r.status_code == 200:
            translated = r.json()["translations"][0]["text"]
            cache[h] = translated
            budget.spend(len(html))
            return translated
        elif r.status_code in (429, 456):
            print("DeepL quota/rate limit (HTTP " + str(r.status_code) + "), falling back to EN")
            budget.exhausted = True
            return html
        else:
            print("DeepL HTTP " + str(r.status_code) + ": " + r.text[:200])
            return html
    except Exception as e:
        print("DeepL exception: " + str(e))
        return html


def translate_product_descriptions(products):
    if not DEEPL_API_KEY:
        print("* DeepL: no DEEPL_API_KEY set, skipping translations")
        return

    cache = load_cache()
    print("* DeepL: cache size at start = " + str(len(cache)))
    budget = Budget(CHAR_BUDGET_PER_RUN)

    cached_hits = 0
    api_calls = 0
    skipped = 0

    # Sort products to translate by description length (shortest first)
    # This maximizes the number of products translated per run.
    items = sorted(
        products.items(),
        key=lambda kv: len(kv[1].get("description_html") or "")
    )

    for sku, p in items:
        html = p.get("description_html") or ""
        if not html.strip():
            continue
        h = _hash(html)
        if h in cache:
            p["description_html"] = cache[h]
            cached_hits += 1
        elif budget.can_spend(len(html)):
            translated = translate_html(html, cache, budget)
            if translated != html:
                p["description_html"] = translated
                api_calls += 1
            else:
                skipped += 1
            time.sleep(0.05)
        else:
            skipped += 1

    save_cache(cache)
    print(
        "* DeepL: cache=" + str(cached_hits) + " hits, "
        + "api=" + str(api_calls) + " new, "
        + "skipped=" + str(skipped) + " (over budget), "
        + "spent=" + str(budget.spent) + "/" + str(budget.budget) + " chars"
    )
    print("* DeepL: cache size at end = " + str(len(cache)))
