import re
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests


WIKI_API = "https://warframe.fandom.com/api.php"
WFM_BASE_V2 = "https://api.warframe.market/v2"

REFINEMENT_PROBS: Dict[str, Dict[str, float]] = {
    "intact": {"common": 25.33, "uncommon": 11.0, "rare": 2.0},
    "exceptional": {"common": 23.33, "uncommon": 13.0, "rare": 4.0},
    "flawless": {"common": 20.0, "uncommon": 17.0, "rare": 6.0},
    "radiant": {"common": 16.67, "uncommon": 20.0, "rare": 10.0},
}

ERA_ALIASES = {
    "lith": "Lith",
    "meso": "Meso",
    "neo": "Neo",
    "axi": "Axi",
    "requiem": "Requiem",
    "古纪": "Lith",
    "前纪": "Meso",
    "中纪": "Neo",
    "后纪": "Axi",
    "安魂": "Requiem",
    "赤毒": "Requiem",
}

FIXED_PRICE_BY_ITEM_KEY = {
    "forma blueprint": 1.0,
}


def normalize_relic_name(value: str) -> str:
    s = value.strip().replace("\u3000", " ")
    s = re.sub(r"\s+Relic$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*遗物$", "", s).strip()

    parts = s.split()
    era_raw: Optional[str] = None
    code_raw: Optional[str] = None

    if len(parts) >= 2:
        era_raw = parts[0]
        code_raw = parts[1]
    else:
        m = re.match(r"^([A-Za-z]+|[\u4e00-\u9fff]{2,})\s*([A-Za-z0-9]+)$", s, flags=re.IGNORECASE)
        if m:
            era_raw = m.group(1)
            code_raw = m.group(2)

    if not era_raw or not code_raw:
        raise ValueError("Invalid relic format. Use 'Meso A6' or '中纪A6'.")

    era = ERA_ALIASES.get(era_raw.lower(), ERA_ALIASES.get(era_raw, era_raw.capitalize()))
    return f"{era} {code_raw.upper()}"


def _strip_html_text(html: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


def _extract_vault_status_from_html(html: str) -> str:
    lower = html.lower()
    if "vaulted" in lower or "已入库" in lower:
        return "vaulted"
    if "unvault" in lower or "available" in lower or "未入库" in lower:
        return "active"
    return "unknown"


def _extract_vault_status_from_categories(body: Any) -> str:
    pages = body.get("query", {}).get("pages", {}) if isinstance(body, dict) else {}
    if not isinstance(pages, dict):
        return "unknown"

    for page in pages.values():
        if not isinstance(page, dict):
            continue
        for cat in page.get("categories", []):
            title = cat.get("title") if isinstance(cat, dict) else None
            if not isinstance(title, str):
                continue
            t = title.lower()
            if "vaulted" in t:
                return "vaulted"
            if "unvault" in t or "available" in t:
                return "active"
    return "unknown"


def _extract_drops_from_wiki_html(html: str) -> List[Tuple[str, str]]:
    tables = re.findall(r"<table[^>]*class=\"[^\"]*wikitable[^\"]*\"[^>]*>(.*?)</table>", html, flags=re.IGNORECASE | re.DOTALL)
    best: List[Tuple[str, str]] = []

    for table in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL)
        drops: List[Tuple[str, str]] = []
        current_rarity: Optional[str] = None

        for row in rows:
            lower = row.lower()
            if "iconcommon" in lower or re.search(r"\bcommon\b", lower):
                current_rarity = "common"
            elif "iconuncommon" in lower or "uncommon" in lower:
                current_rarity = "uncommon"
            elif "iconrare" in lower or re.search(r"\brare\b", lower):
                current_rarity = "rare"

            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL)
            if not cells or not current_rarity:
                continue

            item_cell = cells[0]
            text = _strip_html_text(item_cell)
            if not text:
                links = re.findall(r"<a[^>]*title=\"([^\"]+)\"", item_cell, flags=re.IGNORECASE)
                text = links[0].strip() if links else ""

            if not text or len(text) < 3:
                continue
            if all(x in text.lower() for x in ("intact", "exceptional", "flawless", "radiant")):
                continue
            if "relic" in text.lower() and len(text.split()) <= 3:
                continue

            drops.append((text, current_rarity))

        if len(drops) > len(best):
            best = drops
        if len(drops) >= 6:
            break

    if len(best) < 6:
        raise RuntimeError("Unable to parse drop table from Wiki page")

    return best[:6]


def fetch_single_relic_detail_from_wiki(relic_name: str, timeout_s: float = 20.0) -> Tuple[List[Tuple[str, str]], str]:
    page_name = normalize_relic_name(relic_name)
    session = requests.Session()
    try:
        parse_params = {
            "action": "parse",
            "page": page_name,
            "prop": "text",
            "format": "json",
        }
        response = session.get(WIKI_API, params=parse_params, timeout=timeout_s)
        response.raise_for_status()
        body = response.json()
        html = body.get("parse", {}).get("text", {}).get("*")
        if not isinstance(html, str):
            raise RuntimeError(f"Wiki parse failed: {page_name}")

        drops = _extract_drops_from_wiki_html(html)
        status = _extract_vault_status_from_html(html)

        cat_params = {
            "action": "query",
            "prop": "categories",
            "titles": page_name,
            "cllimit": "200",
            "format": "json",
        }
        try:
            cat_resp = session.get(WIKI_API, params=cat_params, timeout=timeout_s)
            cat_resp.raise_for_status()
            cat_status = _extract_vault_status_from_categories(cat_resp.json())
            if cat_status != "unknown":
                status = cat_status
        except Exception:
            pass

        return drops, status
    finally:
        session.close()


def calc_prob_by_rarity(refinement: str, rarity: str) -> float:
    ref = refinement.lower().strip()
    rar = rarity.lower().strip()
    if ref not in REFINEMENT_PROBS:
        raise ValueError(f"Unknown refinement: {refinement}")
    if rar not in ("common", "uncommon", "rare"):
        raise ValueError(f"Unknown rarity: {rarity}")
    return REFINEMENT_PROBS[ref][rar]


def normalize_item_key(item_name: str) -> str:
    return re.sub(r"\s+", " ", item_name.strip().lower())


def split_item_quantity(item_name: str) -> Tuple[str, int]:
    s = item_name.strip()
    m = re.match(r"^(\d{1,2})\s*[xX×*]\s*(.+)$", s)
    if not m:
        return s, 1

    qty = 1
    try:
        qty = max(1, int(m.group(1)))
    except Exception:
        qty = 1

    core = m.group(2).strip()
    if not core:
        return s, 1
    return core, qty


def new_wfm_session(crossplay: bool = True) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Platform": "pc",
        "Language": "en",
        "Crossplay": "true" if crossplay else "false",
    })
    return session


def _collect_slug_candidates(obj: Any, out: List[Tuple[Optional[str], str]]) -> None:
    if isinstance(obj, dict):
        slug = obj.get("slug") if isinstance(obj.get("slug"), str) else obj.get("url_name")
        if isinstance(slug, str):
            names: List[str] = []
            for key in ("item_name", "name"):
                v = obj.get(key)
                if isinstance(v, str):
                    names.append(v)
            i18n = obj.get("i18n")
            if isinstance(i18n, dict):
                for lang_key in ("en",):
                    lang_entry = i18n.get(lang_key)
                    if isinstance(lang_entry, dict) and isinstance(lang_entry.get("name"), str):
                        names.append(lang_entry.get("name"))

            if names:
                for n in names:
                    out.append((n, slug))
            else:
                out.append((None, slug))

        for v in obj.values():
            _collect_slug_candidates(v, out)
        return

    if isinstance(obj, list):
        for x in obj:
            _collect_slug_candidates(x, out)


def wfm_search_url_name(session: requests.Session, item_name: str, timeout_s: float = 12.0) -> Optional[str]:
    query = item_name.lower().strip()
    target = normalize_item_key(item_name)
    url = f"{WFM_BASE_V2}/items/search/{quote(query)}"

    response = session.get(url, timeout=timeout_s)
    if response.status_code != 200:
        return None

    body = response.json()
    candidates: List[Tuple[Optional[str], str]] = []
    _collect_slug_candidates(body, candidates)
    if not candidates:
        return None

    for name, slug in candidates:
        if isinstance(name, str) and normalize_item_key(name) == target:
            return slug

    return candidates[0][1]


def wfm_lowest_sell_price(
    session: requests.Session,
    url_name: str,
    status_filter: str = "ingame",
    timeout_s: float = 10.0,
) -> Optional[float]:
    url = f"{WFM_BASE_V2}/orders/item/{url_name}"
    response = session.get(url, timeout=timeout_s)
    if response.status_code != 200:
        return None

    body = response.json()
    orders = body.get("data", [])
    if not isinstance(orders, list):
        return None

    candidates: List[float] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if order.get("type") != "sell":
            continue

        user = order.get("user") if isinstance(order.get("user"), dict) else {}
        user_status = user.get("status")
        if status_filter == "ingame" and user_status != "ingame":
            continue
        if status_filter == "online" and user_status not in ("ingame", "online"):
            continue

        price = order.get("platinum")
        if isinstance(price, (int, float)):
            candidates.append(float(price))

    if not candidates:
        return None
    return min(candidates)


def compute_prices_and_ev(
    drops: List[Tuple[str, str]],
    refinement: str,
    status_filter: str = "ingame",
    timeout_s: float = 12.0,
    crossplay: bool = True,
) -> Tuple[List[Dict[str, Any]], float]:
    session = new_wfm_session(crossplay=crossplay)
    slug_cache: Dict[str, Optional[str]] = {}
    price_cache: Dict[str, Optional[float]] = {}
    rows: List[Dict[str, Any]] = []
    ev = 0.0

    try:
        for item_name, rarity in drops:
            prob = calc_prob_by_rarity(refinement, rarity)
            base_name, qty = split_item_quantity(item_name)
            item_key = normalize_item_key(base_name)

            price: Optional[float]
            if item_key in FIXED_PRICE_BY_ITEM_KEY:
                price = FIXED_PRICE_BY_ITEM_KEY[item_key]
            else:
                if item_key not in slug_cache:
                    slug_cache[item_key] = wfm_search_url_name(session, base_name, timeout_s=timeout_s)
                slug = slug_cache[item_key]

                if isinstance(slug, str):
                    if slug not in price_cache:
                        price_cache[slug] = wfm_lowest_sell_price(session, slug, status_filter=status_filter, timeout_s=timeout_s)
                    price = price_cache[slug]
                else:
                    price = None

            if price is not None and qty > 1:
                price *= qty

            value = None
            if price is not None:
                value = (prob / 100.0) * price
                ev += value

            rows.append({
                "item": item_name,
                "rarity": rarity,
                "prob": round(prob, 2),
                "price": price,
                "value": value,
            })
    finally:
        session.close()

    return rows, ev


def calculate_relic_ev(
    relic_name: str,
    refinement: str = "radiant",
    status_filter: str = "ingame",
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    normalized = normalize_relic_name(relic_name)
    drops, vault_status = fetch_single_relic_detail_from_wiki(normalized, timeout_s=timeout_s)
    rows, ev = compute_prices_and_ev(
        drops,
        refinement=refinement,
        status_filter=status_filter,
        timeout_s=timeout_s,
        crossplay=True,
    )

    return {
        "relic": normalized,
        "refinement": refinement,
        "status_filter": status_filter,
        "vault_status": vault_status,
        "ev": round(ev, 4),
        "drops": rows,
    }

