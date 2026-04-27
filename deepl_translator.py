# -*- coding: utf-8 -*-
"""
DeepL translator with persistent caching.

Translates HTML product descriptions EN -> BG using DeepL API.
Caches results in cache/translations.json so each unique description is
only translated once. On subsequent runs only NEW or CHANGED descriptions
hit the API.

Free tier: 500,000 chars/month. We respect a per-run budget so the cron
schedule (every 6h) never exhausts quota in one go.
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
    """DeepL Free uses a different endpoint than Pro."""
    if DEEPL_API_KEY.endswith(":fx"):
        return "https://api-free.deepl.com"
    return "https://api.deepl.com"


def _hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load_cache():
    """Load the persistent translation cache from disk."""
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("WARNING: failed to load cache " + CACHE_PATH + ": " + str(e))
    return {}


def save_cache(cache):
    """Persist the translation cache to disk (creates parent dir if needed)."""
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


class Budget:
    """Tracks how many chars we've spent in this run; refuses calls past limit."""
    def __init__(self, budget):
        self.budget = budget
        self.spent = 0
        self.exhausted = False

    def can_spend(self, n):
        return not self.exhausted and (self.spent + n) <= self.budget

    def spend(self, n):
        self.spent += n


def translate_html(html, cache, budget):
    """Returns BG translation of an HTML string (or original if untranslatable).

    Uses the cache first. If not cached and budget allows, calls DeepL API.
    On failure or no key, returns the original.
    """
    if not html or not DEEPL_API_KEY:
        return html

    h = _hash(html)
    if h in cache:
        return cache[h]

    if not budget.can_spend(len(html)):
        return html  # fall back to EN this cycle

    try:
        r = requests.post(
            _api_base() + "/v2/translate",
            data={
                "auth_key": DEEPL_API_KEY,
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
            # 429 = rate limit, 456 = quota exceeded
            print("DeepL quota exceeded (HTTP " + str(r.status_code) + "), falling back to EN")
            budget.exhausted = True
            return html
        else:
            print("DeepL HTTP " + str(r.status_code) + ": " + r.text[:200])
            return html
    except Exception as e:
        print("DeepL exception: " + str(e))
        return html


def translate_product_descriptions(products):
    """In-place translate description_html for every product in the dict.

    Reports stats at the end.
    """
    if not DEEPL_API_KEY:
        print("* DeepL: no DEEPL_API_KEY set, skipping translations")
        return

    cache = load_cache()
    print("* DeepL: cache size at start = " + str(len(cache)))
    budget = Budget(CHAR_BUDGET_PER_RUN)

    cached_hits = 0
    api_calls = 0
    skipped = 0

    for sku, p in products.items():
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
            time.sleep(0.05)  # be polite to DeepL
        else:
            skipped += 1

    save_cache(cache)
    print("* DeepL: cache=" + str(cached_hits) + " hits, "
          + "api=" + str(api_calls) + " new translations, "
          + "skipped=" + str(skipped) + " (over budget), "
          + "spent=" + str(budget.spent) + "/" + str(budget.budget) + " chars")
    print("* DeepL: cache size at end = " + str(len(cache)))
