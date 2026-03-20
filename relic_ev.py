import argparse
import concurrent.futures
import json
import os
import re
import threading
import time
from urllib.parse import quote
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, List, Optional, Set, Tuple

import requests


WFM_BASE_V2 = "https://api.warframe.market/v2"
PLATFORM = "pc"
LANGUAGE = "en"
CACHE_DEFAULT = ".cache_wfm/items_index_pc_en.json"
I18N_NAME_CACHE_DEFAULT = ".cache_wfm/items_name_map_pc_zh-hans.json"
RELICS_DB_DEFAULT = "relics.json"
WIKI_API = "https://warframe.fandom.com/api.php"
OFFICIAL_RELIC_REWARDS_URL = "https://warframe-web-assets.nyc3.cdn.digitaloceanspaces.com/uploads/cms/hnfvc0o3jnfvc873njb03enrf56.html"
OFFICIAL_RELICS_CACHE_TTL_S = 3600.0
WFM_BASE_V1_FALLBACKS = [
    "https://api.warframe.market/v1",
    "https://warframe.market/api/v1",
]

REFINEMENT_PROBS = {
    "intact":      {"common": 25.33, "uncommon": 11.0, "rare": 2.0},
    "exceptional": {"common": 23.33, "uncommon": 13.0, "rare": 4.0},
    "flawless":    {"common": 20.0,  "uncommon": 17.0, "rare": 6.0},
    "radiant":     {"common": 16.67, "uncommon": 20.0, "rare": 10.0},
}

RARITY_SLOTS = {"common": 3, "uncommon": 2, "rare": 1}

ERA_ALIASES = {
    "lith": "Lith",
    "meso": "Meso",
    "neo": "Neo",
    "axi": "Axi",
    "古纪": "Lith",
    "前纪": "Meso",
    "中纪": "Neo",
    "后纪": "Axi",
    "安魂": "Requiem",
    "requiem": "Requiem",
    "赤毒": "Requiem",
}

ERA_DISPLAY_ALIASES = {
    "Lith": ["古纪"],
    "Meso": ["前纪"],
    "Neo": ["中纪"],
    "Axi": ["后纪"],
    "Requiem": ["赤毒"],
}

_OFFICIAL_RELICS_CACHE: Dict[str, Any] = {"fetched_at": 0.0, "data": {}}
_OFFICIAL_RELICS_LOCK = threading.Lock()


def _extract_bracketed_after_token(text: str, token: str) -> List[str]:
    out: List[str] = []
    start = 0
    n = len(text)
    while True:
        idx = text.find(token, start)
        if idx < 0:
            break
        i = idx + len(token)
        while i < n and text[i] not in "[{":
            i += 1
        if i >= n:
            break

        opener = text[i]
        closer = "]" if opener == "[" else "}"
        depth = 0
        in_str = False
        esc = False
        end = -1
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end > i:
            out.append(text[i:end])
            start = end
        else:
            start = idx + len(token)
    return out


@dataclass
class RelicDrop:
    item_name: str
    rarity: str
    prob: float
    price: Optional[float]
    value: Optional[float]


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


def _is_generic_prime_item_name(item_name: str) -> bool:
    s = item_name.strip()
    # Generic names like "Wukong Prime" lose part specificity for market lookup.
    return bool(re.match(r"^[A-Za-z0-9'\- ]+\s+Prime$", s, flags=re.IGNORECASE))


def _drops_need_wiki_detail(drops: List[Tuple[str, str]]) -> bool:
    if not drops:
        return False
    generic = 0
    for item_name, _ in drops:
        if isinstance(item_name, str) and _is_generic_prime_item_name(item_name):
            generic += 1
    # If most rows are generic "... Prime", prefer wiki detail once and cache it.
    return generic >= 4


def normalize_relic_name(s: str) -> str:
    s = s.strip().replace("\u3000", " ")
    # Accept quantity suffixes like "Meso A6 x3" / "Meso A6*3" and keep only relic id.
    s = re.sub(r"\s*(?:[xX×*＊])\s*\d+\s*$", "", s)
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
        raise ValueError("遗物名格式应类似：Lith A1 / 中纪A9")

    era = ERA_ALIASES.get(era_raw.lower(), ERA_ALIASES.get(era_raw, era_raw.capitalize()))
    code = code_raw.upper()
    return f"{era} {code}"


def calc_prob_by_rarity(refinement: str, rarity: str) -> float:
    refinement = refinement.lower().strip()
    rarity = rarity.lower().strip()
    if refinement not in REFINEMENT_PROBS:
        raise ValueError(f"未知精炼等级: {refinement}")
    if rarity not in ("common", "uncommon", "rare"):
        raise ValueError("rarity 必须是 common/uncommon/rare")
    return REFINEMENT_PROBS[refinement][rarity]


def load_relics_static(path: str) -> Dict[str, List[Tuple[str, str]]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    norm = {}
    for relic, payload in data.items():
        drops = payload
        if isinstance(payload, dict):
            drops = payload.get("drops", [])
        if not isinstance(drops, list):
            continue
        norm[normalize_relic_name(relic)] = [(d[0], d[1].lower()) for d in drops if isinstance(d, list) and len(d) >= 2]
    return norm


def load_relics_status_map(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    out: Dict[str, str] = {}
    if not isinstance(data, dict):
        return out

    for relic, payload in data.items():
        if not isinstance(payload, dict):
            continue
        status = payload.get("vault_status")
        if isinstance(status, str) and status in ("vaulted", "active", "unknown"):
            try:
                out[normalize_relic_name(relic)] = status
            except Exception:
                continue
    return out


def _normalize_rarity(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s in ("common", "uncommon", "rare"):
        return s
    if "common" in s and "uncommon" not in s:
        return "common"
    if "uncommon" in s:
        return "uncommon"
    if "rare" in s:
        return "rare"
    return None


def _parse_relic_record(record: Any) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
    if not isinstance(record, dict):
        return None

    relic_name: Optional[str] = None
    tier = record.get("tier")
    relic_code = record.get("relicName")
    if isinstance(tier, str) and isinstance(relic_code, str):
        relic_name = f"{tier} {relic_code}"
    else:
        for k in ("name", "relic", "relicName", "id"):
            v = record.get(k)
            if isinstance(v, str) and len(v.strip()) >= 3:
                relic_name = v
                break

    if not relic_name:
        return None

    rewards_raw = None
    for k in ("rewards", "drops", "items", "loot"):
        if isinstance(record.get(k), list):
            rewards_raw = record.get(k)
            break
    if rewards_raw is None:
        return None

    drops: List[Tuple[str, str]] = []
    for r in rewards_raw:
        item_name: Optional[str] = None
        rarity: Optional[str] = None

        if isinstance(r, list) and len(r) >= 2:
            if isinstance(r[0], str):
                item_name = r[0]
            rarity = _normalize_rarity(r[1])
        elif isinstance(r, dict):
            for key in ("itemName", "item_name", "name", "item"):
                v = r.get(key)
                if isinstance(v, str):
                    item_name = v
                    break
            rarity = _normalize_rarity(r.get("rarity") or r.get("tier") or r.get("dropRarity"))

        if item_name and rarity:
            drops.append((item_name, rarity))

    if not drops:
        return None

    return normalize_relic_name(relic_name), drops


def parse_remote_relics_payload(payload: Any) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {}

    # Already in local cache shape: {"Lith A1": [["item", "common"], ...]}
    if isinstance(payload, dict) and payload and all(isinstance(v, list) for v in payload.values()):
        for relic, drops in payload.items():
            if not isinstance(relic, str):
                continue
            parsed = _parse_relic_record({"name": relic, "rewards": drops})
            if parsed:
                out[parsed[0]] = parsed[1]
        if out:
            return out

    seen: Set[int] = set()

    def walk(obj: Any) -> None:
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)

        parsed = _parse_relic_record(obj)
        if parsed:
            out[parsed[0]] = parsed[1]
            return

        if isinstance(obj, list):
            for x in obj:
                walk(x)
            return

        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)

    walk(payload)

    return out


def _extract_json_blobs_with_keyword(text: str, keyword: str, max_blobs: int = 24) -> List[str]:
    blobs: List[str] = []
    pos = 0
    n = len(text)

    while len(blobs) < max_blobs:
        idx = text.find(keyword, pos)
        if idx < 0:
            break

        start = idx
        while start >= 0 and text[start] not in "[{":
            start -= 1
        if start < 0:
            pos = idx + len(keyword)
            continue

        opener = text[start]
        closer = "]" if opener == "[" else "}"
        depth = 0
        in_str = False
        esc = False
        end = -1

        for i in range(start, n):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if end > start:
            blob = text[start:end]
            if keyword in blob:
                blobs.append(blob)
            pos = end
        else:
            pos = idx + len(keyword)

    return blobs


def _extract_relics_from_official_rewards_html(html: str, debug: bool = False) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {}

    start = html.lower().find('id="relicrewards"')
    if start < 0:
        return out

    end = html.lower().find('id="keyrewards"', start)
    if end < 0:
        end = min(len(html), start + 800000)

    section = html[start:end]
    relic_blocks = re.finditer(
        r"<tr>\s*<th[^>]*colspan=\"?\d+\"?[^>]*>([^<]*?\bRelic\b[^<]*)</th>\s*</tr>(.*?)"
        r"(?=<tr>\s*<th[^>]*colspan=\"?\d+\"?[^>]*>[^<]*?\bRelic\b[^<]*</th>\s*</tr>|$)",
        section,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for m in relic_blocks:
        relic_header = _strip_html_text(m.group(1))
        if not relic_header:
            continue
        try:
            relic_name = normalize_relic_name(re.sub(r"\s*Relic\s*$", "", relic_header, flags=re.IGNORECASE))
        except Exception:
            continue

        rows_html = m.group(2)
        row_matches = re.findall(r"<tr>(.*?)</tr>", rows_html, flags=re.IGNORECASE | re.DOTALL)
        item_rows: List[str] = []
        for row in row_matches:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
            if not cells:
                continue
            texts = [_strip_html_text(c) for c in cells]
            if not any(texts):
                continue
            item_text = texts[0]
            if not item_text or len(item_text) < 2:
                continue
            item_text = re.sub(r"\s*\(.*?\)\s*$", "", item_text).strip()
            if "relic" in item_text.lower():
                continue
            item_rows.append(item_text)

        if len(item_rows) >= 6:
            # Official relic table rows are ordered as: rare, uncommon, uncommon, common, common, common.
            rows6 = item_rows[:6]
            drops: List[Tuple[str, str]] = []
            for idx, item_name in enumerate(rows6):
                if idx == 0:
                    rarity = "rare"
                elif idx < 3:
                    rarity = "uncommon"
                else:
                    rarity = "common"
                drops.append((item_name, rarity))
            out[relic_name] = drops

    if debug:
        print(f"[DEBUG] official rewards html relic blocks: {len(out)}")
    return out


def fetch_relics_from_official_rewards(timeout_s: float = 20.0, debug: bool = False) -> Dict[str, List[Tuple[str, str]]]:
    now = time.time()
    with _OFFICIAL_RELICS_LOCK:
        cached_at = float(_OFFICIAL_RELICS_CACHE.get("fetched_at", 0.0) or 0.0)
        cached_data = _OFFICIAL_RELICS_CACHE.get("data", {})
        if isinstance(cached_data, dict) and cached_data and (now - cached_at) < OFFICIAL_RELICS_CACHE_TTL_S:
            if debug:
                print(f"[DEBUG] official rewards cache hit: {len(cached_data)} relics")
            return cached_data

    session = _new_wiki_session()
    session.headers.update({"Accept": "text/html,application/json"})

    r = session.get(OFFICIAL_RELIC_REWARDS_URL, timeout=timeout_s)
    if debug:
        print(f"[DEBUG] official rewards page -> {r.status_code}")
    r.raise_for_status()
    html = r.text

    html_db = _extract_relics_from_official_rewards_html(html, debug=debug)
    if html_db:
        with _OFFICIAL_RELICS_LOCK:
            _OFFICIAL_RELICS_CACHE["fetched_at"] = now
            _OFFICIAL_RELICS_CACHE["data"] = html_db
        if debug:
            print(f"[DEBUG] official rewards parsed relics: {len(html_db)}")
        return html_db

    candidates: List[str] = []
    candidates.extend(_extract_json_blobs_with_keyword(html, '"relicName"'))
    for token in ("relicRewards", "relic_rewards", '"relics"', "window.__NUXT__", "__NEXT_DATA__"):
        candidates.extend(_extract_bracketed_after_token(html, token))
    script_blocks = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
    for s in script_blocks:
        if '"relicName"' in s:
            candidates.append(s.strip())
            candidates.extend(_extract_json_blobs_with_keyword(s, '"relicName"'))
        for token in ("relicRewards", "relic_rewards", '"relics"'):
            candidates.extend(_extract_bracketed_after_token(s, token))

    # Some CMS pages store relic data in external JSON assets.
    asset_urls: List[str] = []
    for m in re.finditer(r"(?:src|href)=\"([^\"]+)\"", html, flags=re.IGNORECASE):
        u = m.group(1)
        if not isinstance(u, str):
            continue
        lu = u.lower()
        if ".json" not in lu:
            continue
        if not any(k in lu for k in ("relic", "reward", "drop")):
            continue
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = "https://warframe-web-assets.nyc3.cdn.digitaloceanspaces.com" + u
        asset_urls.append(u)

    for u in sorted(set(asset_urls)):
        try:
            rr = session.get(u, timeout=timeout_s)
            rr.raise_for_status()
            candidates.append(rr.text)
            if debug:
                print(f"[DEBUG] official rewards asset fetched: {u} ({len(rr.text)} chars)")
        except Exception as e:
            if debug:
                print(f"[DEBUG] official rewards asset fetch failed: {u} ({e})")

    seen_raw: Set[str] = set()
    db: Dict[str, List[Tuple[str, str]]] = {}
    for raw in candidates:
        raw = raw.strip()
        if not raw or raw in seen_raw:
            continue
        seen_raw.add(raw)

        try:
            payload = json.loads(raw)
        except Exception:
            continue

        parsed = parse_remote_relics_payload(payload)
        if len(parsed) > len(db):
            db = parsed

    if debug:
        print(f"[DEBUG] official rewards parsed relics: {len(db)}")

    with _OFFICIAL_RELICS_LOCK:
        _OFFICIAL_RELICS_CACHE["fetched_at"] = now
        _OFFICIAL_RELICS_CACHE["data"] = db

    return db


def _new_wiki_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "User-Agent": "relic-ev-tool/1.0",
    })
    return s


def _extract_drops_from_wiki_html(html: str) -> List[Tuple[str, str]]:
    table_matches = re.findall(
        r"(<table[^>]*class=\"[^\"]*(?:wikitable|article-table)[^\"]*\"[^>]*>.*?</table>)",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not table_matches:
        return []

    all_drops: List[Tuple[str, str]] = []

    for table_html in table_matches:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)
        cur_rarity: Optional[str] = None
        drops: List[Tuple[str, str]] = []

        for row in rows:
            lower = row.lower()
            if "iconcommon" in lower or re.search(r"\bcommon\b", lower):
                cur_rarity = "common"
            elif "iconuncommon" in lower or "uncommon" in lower:
                cur_rarity = "uncommon"
            elif "iconrare" in lower or re.search(r"\brare\b", lower):
                cur_rarity = "rare"

            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.DOTALL | re.IGNORECASE)
            if not cells or not cur_rarity:
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

            drops.append((text, cur_rarity))

        if len(drops) >= 6:
            all_drops = drops
            break
        if len(drops) > len(all_drops):
            all_drops = drops

    return all_drops


def fetch_single_relic_detail_from_wiki(
    relic_name: str,
    timeout_s: float = 20.0,
    debug: bool = False,
    session: Optional[requests.Session] = None,
) -> Tuple[List[Tuple[str, str]], str]:
    own_session = session is None
    s = session or _new_wiki_session()
    try:
        page_name = normalize_relic_name(relic_name)
        params = {
            "action": "parse",
            "page": page_name,
            "prop": "text",
            "format": "json",
        }
        r = s.get(WIKI_API, params=params, timeout=timeout_s)
        if debug:
            print(f"[DEBUG] wiki parse {page_name} -> {r.status_code}")
        r.raise_for_status()
        body = r.json()
        html = body.get("parse", {}).get("text", {}).get("*")
        if not isinstance(html, str):
            raise RuntimeError(f"Wiki 页面解析失败: {page_name}")

        drops = _extract_drops_from_wiki_html(html)
        if not drops:
            raise RuntimeError(f"Wiki 未解析到掉落表: {page_name}")

        status = _extract_vault_status_from_html(html)
        try:
            cat_params = {
                "action": "query",
                "prop": "categories",
                "titles": page_name,
                "cllimit": "200",
                "format": "json",
            }
            cat_resp = s.get(WIKI_API, params=cat_params, timeout=timeout_s)
            cat_resp.raise_for_status()
            cat_status = _extract_vault_status_from_categories(cat_resp.json())
            if cat_status != "unknown":
                status = cat_status
        except Exception:
            pass

        return drops, status
    finally:
        if own_session:
            s.close()


def fetch_single_relic_from_wiki(relic_name: str, timeout_s: float = 20.0, debug: bool = False) -> List[Tuple[str, str]]:
    drops, _ = fetch_single_relic_detail_from_wiki(relic_name, timeout_s=timeout_s, debug=debug)
    return drops


def fetch_relic_titles_from_wiki(timeout_s: float = 20.0, debug: bool = False) -> List[str]:
    session = _new_wiki_session()
    titles: List[str] = []
    cmcontinue: Optional[str] = None

    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "Category:Relic",
            "cmtype": "page",
            "cmlimit": "500",
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        r = session.get(WIKI_API, params=params, timeout=timeout_s)
        r.raise_for_status()
        body = r.json()

        members = body.get("query", {}).get("categorymembers", [])
        for m in members:
            title = m.get("title") if isinstance(m, dict) else None
            if isinstance(title, str):
                try:
                    titles.append(normalize_relic_name(title))
                except Exception:
                    continue

        cmcontinue = body.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break

    if debug:
        print(f"[DEBUG] wiki relic titles fetched: {len(titles)}")
    return sorted(set(titles))


def save_relics_static(
    path: str,
    data: Dict[str, List[Tuple[str, str]]],
    status_map: Optional[Dict[str, str]] = None,
) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    payload: Dict[str, Any] = {}
    for relic, drops in data.items():
        row = {
            "drops": [[item, rarity] for item, rarity in drops],
            "vault_status": "unknown",
        }
        if status_map and status_map.get(relic) in ("vaulted", "active", "unknown"):
            row["vault_status"] = status_map.get(relic)
        payload[relic] = row

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def refresh_relics_db(path: str = RELICS_DB_DEFAULT, timeout_s: float = 20.0, debug: bool = False) -> Dict[str, List[Tuple[str, str]]]:
    titles = fetch_relic_titles_from_wiki(timeout_s=timeout_s, debug=debug)
    db: Dict[str, List[Tuple[str, str]]] = {}
    status_map: Dict[str, str] = {}
    errors: List[str] = []
    session = _new_wiki_session()

    # Try official static rewards first, then补齐wiki缺失项。
    try:
        official_db = fetch_relics_from_official_rewards(timeout_s=timeout_s, debug=debug)
        if official_db:
            db.update(official_db)
            for relic_name in official_db.keys():
                status_map[relic_name] = "unknown"
    except Exception as e:
        if debug:
            print(f"[DEBUG] official rewards fetch failed: {e}")

    for i, title in enumerate(titles, start=1):
        if title in db:
            continue
        try:
            drops, status = fetch_single_relic_detail_from_wiki(title, timeout_s=timeout_s, debug=False, session=session)
            db[title] = drops
            status_map[title] = status
        except Exception as e:
            errors.append(f"{title}({e})")
        if debug and i % 50 == 0:
            print(f"[DEBUG] wiki full refresh progress: {i}/{len(titles)}")

    session.close()

    if not db:
        raise RuntimeError("在线遗物数据获取失败: Wiki 返回为空")

    save_relics_static(path, db, status_map=status_map)
    if debug:
        print(f"[DEBUG] relic db refreshed: {path} ({len(db)} relics, errors={len(errors)})")
    return db


def extract_relic_options(static_db: Dict[str, List[Tuple[str, str]]]) -> Dict[str, List[str]]:
    options: Dict[str, Set[str]] = {
        "Lith": set(),
        "Meso": set(),
        "Neo": set(),
        "Axi": set(),
        "Requiem": set(),
    }
    for relic_name in static_db.keys():
        parts = relic_name.split()
        if len(parts) < 2:
            continue
        era = parts[0]
        code = " ".join(parts[1:])
        if era in options:
            options[era].add(code)

    return {k: sorted(v) for k, v in options.items()}


def get_relic_drops_auto(
    relic_name: str,
    refinement: str,
    db_path: str = RELICS_DB_DEFAULT,
    timeout_s: float = 20.0,
    debug: bool = False,
) -> List[RelicDrop]:
    normalized = normalize_relic_name(relic_name)

    static_db: Dict[str, List[Tuple[str, str]]] = {}
    status_map: Dict[str, str] = {}
    if os.path.exists(db_path):
        static_db = load_relics_static(db_path)
        status_map = load_relics_status_map(db_path)

    if normalized in static_db and _drops_need_wiki_detail(static_db[normalized]):
        if debug:
            print(f"[DEBUG] refreshing generic prime drops from wiki: {normalized}")
        try:
            wiki_drops, wiki_status = fetch_single_relic_detail_from_wiki(normalized, timeout_s=timeout_s, debug=debug)
            if wiki_drops and not _drops_need_wiki_detail(wiki_drops):
                static_db[normalized] = wiki_drops
                status_map[normalized] = wiki_status
                save_relics_static(db_path, static_db, status_map=status_map)
                if debug:
                    print(f"[DEBUG] upgraded drops to detailed names: {normalized}")
        except Exception as e:
            if debug:
                print(f"[DEBUG] wiki detail upgrade skipped: {normalized} ({e})")

    if normalized not in static_db:
        if debug:
            print(f"[DEBUG] relic not found locally, fetching from wiki: {normalized}")

        drops: Optional[List[Tuple[str, str]]] = None
        status = "unknown"

        try:
            official_db = fetch_relics_from_official_rewards(timeout_s=timeout_s, debug=debug)
            drops = official_db.get(normalized)
            if drops and debug:
                print(f"[DEBUG] relic found from official rewards: {normalized}")
        except Exception as e:
            if debug:
                print(f"[DEBUG] official rewards lookup failed: {e}")

        if not drops:
            try:
                drops, status = fetch_single_relic_detail_from_wiki(normalized, timeout_s=timeout_s, debug=debug)
            except Exception as e:
                # Show a stable, user-friendly message in GUI batch notes.
                raise RuntimeError(f"未收录/疑似OCR误识别: {normalized}") from e

        static_db[normalized] = drops
        status_map[normalized] = status
        save_relics_static(db_path, static_db, status_map=status_map)

    if normalized not in static_db:
        raise RuntimeError(f"未收录/疑似OCR误识别: {normalized}")

    return get_relic_drops(normalized, refinement, static_db)


def get_relic_vault_status_auto(
    relic_name: str,
    db_path: str = RELICS_DB_DEFAULT,
    timeout_s: float = 20.0,
    debug: bool = False,
) -> str:
    normalized = normalize_relic_name(relic_name)
    status_map = load_relics_status_map(db_path)
    cached = status_map.get(normalized)
    if cached in ("vaulted", "active", "unknown"):
        return cached

    try:
        _, status = fetch_single_relic_detail_from_wiki(normalized, timeout_s=timeout_s, debug=debug)
    except Exception:
        return "unknown"

    status_map[normalized] = status
    static_db: Dict[str, List[Tuple[str, str]]] = {}
    if os.path.exists(db_path):
        static_db = load_relics_static(db_path)
    save_relics_static(db_path, static_db, status_map=status_map)
    return status


def get_relic_drops(relic_name: str, refinement: str, static_db: Dict[str, List[Tuple[str, str]]]) -> List[RelicDrop]:
    relic_name = normalize_relic_name(relic_name)
    if relic_name not in static_db:
        raise KeyError(f"静态库中找不到遗物：{relic_name}")

    drops = static_db[relic_name]

    rarity_count = {"common": 0, "uncommon": 0, "rare": 0}
    for _, rar in drops:
        if rar not in rarity_count:
            raise ValueError(f"{relic_name} 包含未知稀有度: {rar}")
        rarity_count[rar] += 1

    for rar, need in RARITY_SLOTS.items():
        if rarity_count[rar] != need:
            raise ValueError(f"{relic_name} 的 {rar} 数量应为 {need}，但得到 {rarity_count[rar]}")

    result: List[RelicDrop] = []
    for item_name, rar in drops:
        prob = calc_prob_by_rarity(refinement, rar)
        result.append(RelicDrop(item_name=item_name, rarity=rar, prob=prob, price=None, value=None))
    return result


# ---------------- warframe.market ----------------

def new_wfm_session(crossplay: bool = True) -> requests.Session:
    s = requests.Session()
    # 这些 header 在不少地区/网络环境下能避免奇怪的返回
    s.headers.update({
        "Accept": "application/json",
        "Platform": PLATFORM,
        "Language": LANGUAGE,
        "Crossplay": "true" if crossplay else "false",
    })
    return s


def normalize_item_key(item_name: str) -> str:
    return re.sub(r"\s+", " ", item_name.strip().lower())


def normalize_item_key_loose(item_name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", item_name.lower())).strip()


def split_item_quantity(item_name: str) -> Tuple[str, int]:
    s = item_name.strip()
    m = re.match(r"^(\d{1,2})\s*[xX×*]\s*(.+)$", s)
    if not m:
        return s, 1
    try:
        qty = int(m.group(1))
    except Exception:
        qty = 1
    core = m.group(2).strip()
    if qty < 1:
        qty = 1
    if not core:
        return s, 1
    return core, qty


DEFAULT_PRICE_BY_ITEM_KEY = {
    "forma blueprint": 1.0,
}


def iter_item_pairs(obj: Any, out: Dict[str, str], seen: Set[int]) -> None:
    oid = id(obj)
    if oid in seen:
        return
    seen.add(oid)

    if isinstance(obj, dict):
        item_name = obj.get("item_name")
        url_name = obj.get("url_name")
        if isinstance(item_name, str) and isinstance(url_name, str):
            out[normalize_item_key(item_name)] = url_name
        for v in obj.values():
            iter_item_pairs(v, out, seen)
        return

    if isinstance(obj, list):
        for x in obj:
            iter_item_pairs(x, out, seen)


def build_legacy_items_index_from_response(payload: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    iter_item_pairs(payload, out, set())
    return out


def build_v2_items_index_from_response(payload: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(payload, dict):
        return out

    data = payload.get("data")
    if not isinstance(data, list):
        return out

    for item in data:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        i18n = item.get("i18n")
        if not isinstance(slug, str) or not isinstance(i18n, dict):
            continue

        name = None
        lang_entry = i18n.get(LANGUAGE)
        if isinstance(lang_entry, dict) and isinstance(lang_entry.get("name"), str):
            name = lang_entry.get("name")
        elif isinstance(i18n.get("en"), dict) and isinstance(i18n.get("en", {}).get("name"), str):
            name = i18n.get("en", {}).get("name")

        if isinstance(name, str):
            out[normalize_item_key(name)] = slug

    return out


def build_v2_items_name_map_from_response(payload: Any, target_lang: str = "zh-hans") -> Dict[str, str]:
    """Build english-name -> localized-name map from /v2/items payload."""
    out: Dict[str, str] = {}
    if not isinstance(payload, dict):
        return out

    data = payload.get("data")
    if not isinstance(data, list):
        return out

    for item in data:
        if not isinstance(item, dict):
            continue
        i18n = item.get("i18n")
        if not isinstance(i18n, dict):
            continue

        en_entry = i18n.get("en")
        zh_entry = i18n.get(target_lang)
        en_name = en_entry.get("name") if isinstance(en_entry, dict) else None
        zh_name = zh_entry.get("name") if isinstance(zh_entry, dict) else None
        if isinstance(en_name, str) and isinstance(zh_name, str) and en_name.strip() and zh_name.strip():
            out[normalize_item_key(en_name)] = zh_name.strip()

    return out


def load_items_index_cache(cache_path: str, ttl_h: float, debug: bool = False) -> Optional[Dict[str, str]]:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        if debug:
            print(f"[DEBUG] cache read failed: {cache_path} ({e})")
        return None

    created_at = data.get("created_at")
    items = data.get("items")
    if not isinstance(created_at, (int, float)) or not isinstance(items, dict):
        return None

    age_s = time.time() - float(created_at)
    if age_s > ttl_h * 3600:
        if debug:
            print(f"[DEBUG] cache expired: age={age_s:.0f}s ttl={ttl_h * 3600:.0f}s")
        return None

    if debug:
        print(f"[DEBUG] cache hit: {cache_path} ({len(items)} items)")
    return {normalize_item_key(k): v for k, v in items.items() if isinstance(k, str) and isinstance(v, str)}


def save_items_index_cache(cache_path: str, source_url: str, items: Dict[str, str], debug: bool = False) -> None:
    parent = os.path.dirname(cache_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {
        "created_at": time.time(),
        "platform": PLATFORM,
        "language": LANGUAGE,
        "source_url": source_url,
        "item_count": len(items),
        "items": items,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if debug:
        print(f"[DEBUG] cache saved: {cache_path} ({len(items)} items)")


def load_items_name_map_cache(cache_path: str, ttl_h: float, debug: bool = False) -> Optional[Dict[str, str]]:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        if debug:
            print(f"[DEBUG] name-map cache read failed: {cache_path} ({e})")
        return None

    created_at = data.get("created_at")
    items = data.get("items")
    if not isinstance(created_at, (int, float)) or not isinstance(items, dict):
        return None

    age_s = time.time() - float(created_at)
    if age_s > ttl_h * 3600:
        if debug:
            print(f"[DEBUG] name-map cache expired: age={age_s:.0f}s ttl={ttl_h * 3600:.0f}s")
        return None

    if debug:
        print(f"[DEBUG] name-map cache hit: {cache_path} ({len(items)} items)")
    return {normalize_item_key(k): v for k, v in items.items() if isinstance(k, str) and isinstance(v, str)}


def save_items_name_map_cache(cache_path: str, source_url: str, items: Dict[str, str], debug: bool = False) -> None:
    parent = os.path.dirname(cache_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {
        "created_at": time.time(),
        "platform": PLATFORM,
        "source_url": source_url,
        "item_count": len(items),
        "items": items,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if debug:
        print(f"[DEBUG] name-map cache saved: {cache_path} ({len(items)} items)")


def get_items_name_map_zh(
    session: requests.Session,
    cache_path: str = I18N_NAME_CACHE_DEFAULT,
    cache_ttl_h: float = 72.0,
    timeout_s: float = 12.0,
    debug: bool = False,
) -> Dict[str, str]:
    """Fetch or load cached english->zh-hans name map from /v2/items."""
    cached = load_items_name_map_cache(cache_path, cache_ttl_h, debug=debug)
    if cached is not None:
        return cached

    url = f"{WFM_BASE_V2}/items"
    try:
        r = session.get(url, timeout=timeout_s, headers={"Language": "zh-hans"})
        if debug:
            print(f"[DEBUG] fetch zh name-map: {url} -> {r.status_code}")
        r.raise_for_status()
        body = r.json()
    except Exception as e:
        if debug:
            print(f"[DEBUG] fetch zh name-map failed: {e}")
        return {}

    name_map = build_v2_items_name_map_from_response(body, target_lang="zh-hans")
    if name_map:
        save_items_name_map_cache(cache_path, url, name_map, debug=debug)
    return name_map


def detect_items_index_endpoint(
    session: requests.Session,
    timeout_s: float = 12.0,
    debug: bool = False,
) -> Tuple[str, Dict[str, str]]:
    candidates: List[Tuple[str, str]] = [(f"{WFM_BASE_V2}/items", "v2_items")]
    for base in WFM_BASE_V1_FALLBACKS:
        candidates.extend([
            (f"{base}/items", "legacy"),
            (f"{base}/items?include=item_name,url_name", "legacy"),
            (f"{base}/items/list", "legacy"),
            (f"{base}/tools/items", "legacy"),
        ])

    for url, parser_type in candidates:
        try:
            r = session.get(url, timeout=timeout_s)
            if debug:
                print(f"[DEBUG] detect endpoint: {url} -> {r.status_code}")
        except requests.RequestException as e:
            if debug:
                print(f"[DEBUG] detect endpoint request failed: {url} ({e})")
            continue

        if r.status_code != 200:
            continue

        try:
            j = r.json()
        except ValueError:
            if debug:
                print(f"[DEBUG] detect endpoint invalid JSON: {url}")
            continue

        if parser_type == "v2_items":
            items_index = build_v2_items_index_from_response(j)
        else:
            items_index = build_legacy_items_index_from_response(j)

        if items_index:
            if debug:
                print(f"[DEBUG] endpoint chosen: {url} ({len(items_index)} items)")
            return url, items_index

        if debug:
            print(f"[DEBUG] endpoint has no parsable item list: {url}")

    raise RuntimeError("无法探测可用的 items 列表端点")


def get_items_index(
    session: requests.Session,
    cache_path: str,
    cache_ttl_h: float,
    timeout_s: float,
    debug: bool = False,
) -> Dict[str, str]:
    cached = load_items_index_cache(cache_path, cache_ttl_h, debug=debug)
    if cached is not None:
        return cached

    source_url, items_index = detect_items_index_endpoint(session, timeout_s=timeout_s, debug=debug)
    save_items_index_cache(cache_path, source_url, items_index, debug=debug)
    return items_index


def wfm_search_url_name(session: requests.Session, item_name: str, debug: bool = False) -> Optional[str]:
    """
    Compatible parser for multiple warframe.market search response shapes.
    """
    query = item_name.lower().strip()
    target = normalize_item_key(item_name)
    target_loose = normalize_item_key_loose(item_name)

    def collect_candidates(obj: Any, out: List[Tuple[Optional[str], str]], seen: Set[int]) -> None:
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)

        if isinstance(obj, dict):
            slug = obj.get("slug")
            if not isinstance(slug, str):
                slug = obj.get("url_name")

            if isinstance(slug, str):
                names: List[str] = []
                for k in ("item_name", "name"):
                    v = obj.get(k)
                    if isinstance(v, str):
                        names.append(v)

                i18n = obj.get("i18n")
                if isinstance(i18n, dict):
                    for lang_key in (LANGUAGE, "en"):
                        lang_entry = i18n.get(lang_key)
                        if isinstance(lang_entry, dict) and isinstance(lang_entry.get("name"), str):
                            names.append(lang_entry.get("name"))

                if names:
                    for n in names:
                        out.append((n, slug))
                else:
                    out.append((None, slug))

            for v in obj.values():
                collect_candidates(v, out, seen)
            return

        if isinstance(obj, list):
            for x in obj:
                collect_candidates(x, out, seen)

    urls = [f"{WFM_BASE_V2}/items/search/{quote(query)}"]
    for base in WFM_BASE_V1_FALLBACKS:
        urls.append(f"{base}/items/search/{quote(query)}")

    for url in urls:
        try:
            r = session.get(url, timeout=12.0)
            if debug:
                print(f"[DEBUG] search endpoint: {url} -> {r.status_code}")
            if r.status_code != 200:
                continue
            body = r.json()
        except Exception as e:
            if debug:
                print(f"[DEBUG] search request failed: {url} ({e})")
            continue

        candidates: List[Tuple[Optional[str], str]] = []
        collect_candidates(body, candidates, set())
        if not candidates:
            if debug:
                print(f"[DEBUG] search returned no parsable candidates for '{item_name}'")
            continue

        for name, slug in candidates:
            if isinstance(name, str) and normalize_item_key(name) == target:
                return slug

        for name, slug in candidates:
            if isinstance(name, str) and normalize_item_key_loose(name) == target_loose:
                if debug:
                    print(f"[DEBUG] loose matched '{item_name}' -> '{name}'")
                return slug

        if debug:
            print(f"[DEBUG] no exact name match for '{item_name}', fallback to first candidate")
        return candidates[0][1]

    if debug:
        print(f"[DEBUG] search failed to resolve url_name: {item_name}")
    return None


def wfm_lowest_sell_price(
    session: requests.Session,
    url_name: str,
    status_filter: str = "ingame",
    timeout_s: float = 10.0,
    debug: bool = False,
) -> Optional[float]:
    """
    status_filter:
      - "ingame": 只取 ingame
      - "online": online + ingame 都算（更容易有价格）
      - "any": 不过滤状态
    """
    orders: List[Dict[str, Any]] = []

    v2_url = f"{WFM_BASE_V2}/orders/item/{url_name}"
    try:
        r = session.get(v2_url, timeout=timeout_s)
        if debug:
            print(f"[DEBUG] orders {url_name} @ v2 -> {r.status_code}")
        if r.status_code != 404:
            r.raise_for_status()
            body = r.json()
            parsed_orders = body.get("data", [])
            if isinstance(parsed_orders, list):
                orders = parsed_orders
    except Exception as e:
        if debug:
            print(f"[DEBUG] orders parse failed for {url_name} @ v2: {e}")

    # Fallback for environments where v2 orders is unavailable.
    if not orders:
        for base in WFM_BASE_V1_FALLBACKS:
            url = f"{base}/items/{url_name}/orders"
            try:
                r = session.get(url, timeout=timeout_s)
            except requests.RequestException as e:
                if debug:
                    print(f"[DEBUG] orders request failed for {url_name} @ {base}: {e}")
                continue

            if debug:
                print(f"[DEBUG] orders {url_name} @ {base} -> {r.status_code}")

            if r.status_code == 404:
                continue

            try:
                r.raise_for_status()
                body = r.json()
            except Exception as e:
                if debug:
                    print(f"[DEBUG] orders parse failed for {url_name} @ {base}: {e}")
                continue

            parsed_orders = body.get("payload", {}).get("orders", [])
            if isinstance(parsed_orders, list):
                orders = parsed_orders
                break

    if not orders:
        return None

    candidates: List[float] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        order_type = o.get("type", o.get("order_type"))
        if order_type != "sell":
            continue
        user = o.get("user", {})
        status = user.get("status") if isinstance(user, dict) else None

        if status_filter == "ingame":
            if status != "ingame":
                continue
        elif status_filter == "online":
            if status not in ("ingame", "online"):
                continue
        elif status_filter == "any":
            pass

        price = o.get("platinum")
        if isinstance(price, (int, float)):
            candidates.append(float(price))

    if not candidates:
        return None
    return min(candidates)


def compute_prices_and_ev(
    drops: List[RelicDrop],
    status_filter: str = "ingame",
    sleep_s: float = 0.12,
    debug: bool = False,
    cache_path: str = CACHE_DEFAULT,
    cache_ttl_h: float = 24.0,
    timeout_s: float = 12.0,
    crossplay: bool = True,
    session: Optional[requests.Session] = None,
    item_slug_cache: Optional[Dict[str, Optional[str]]] = None,
    price_cache: Optional[Dict[str, Optional[float]]] = None,
    shared_item_index: Optional[Dict[str, str]] = None,
    max_workers: int = 1,
    prefer_index_first: bool = True,
):
    own_session = session is None
    session = session or new_wfm_session(crossplay=crossplay)

    ev = 0.0
    out: List[RelicDrop] = []
    item_index: Dict[str, str] = shared_item_index if shared_item_index is not None else {}
    index_attempted = bool(item_index)
    slug_cache = item_slug_cache if item_slug_cache is not None else {}
    p_cache = price_cache if price_cache is not None else {}

    # Fixed-price items are intentionally not tradable on market (e.g. Forma Blueprint).
    needs_market_lookup = any(
        normalize_item_key(split_item_quantity(d.item_name)[0]) not in DEFAULT_PRICE_BY_ITEM_KEY
        for d in drops
    )

    slug_by_item: Dict[str, Optional[str]] = {}

    if needs_market_lookup and prefer_index_first and not index_attempted:
        index_attempted = True
        try:
            fetched = get_items_index(
                session,
                cache_path=cache_path,
                cache_ttl_h=cache_ttl_h,
                timeout_s=timeout_s,
                debug=debug,
            )
            item_index.update(fetched)
        except Exception as e:
            if debug:
                print(f"[DEBUG] build items index failed: {e}")

    for d in drops:
        base_item_name, item_qty = split_item_quantity(d.item_name)
        item_key = normalize_item_key(base_item_name)

        if item_key in DEFAULT_PRICE_BY_ITEM_KEY:
            slug_cache[item_key] = None
            slug_by_item[item_key] = None
            if debug:
                print(f"[DEBUG] fixed price item, skip market lookup: '{base_item_name}'")
            continue

        if item_key in slug_cache:
            slug_by_item[item_key] = slug_cache[item_key]
            continue

        url_name: Optional[str] = None
        if item_index:
            exact = item_index.get(item_key)
            if exact:
                url_name = exact
            else:
                target_loose = normalize_item_key_loose(base_item_name)
                for k, v in item_index.items():
                    if normalize_item_key_loose(k) == target_loose:
                        if debug:
                            print(f"[DEBUG] index loose matched '{base_item_name}' -> '{k}'")
                        url_name = v
                        break

        if not url_name and needs_market_lookup and not index_attempted:
            index_attempted = True
            try:
                fetched = get_items_index(
                    session,
                    cache_path=cache_path,
                    cache_ttl_h=cache_ttl_h,
                    timeout_s=timeout_s,
                    debug=debug,
                )
                item_index.update(fetched)
            except Exception as e:
                if debug:
                    print(f"[DEBUG] build items index failed: {e}")

            exact = item_index.get(item_key)
            if exact:
                url_name = exact

        if not url_name:
            # /search 在一些环境会直接 404，仅作为兜底。
            url_name = wfm_search_url_name(session, base_item_name, debug=debug)

        slug_cache[item_key] = url_name
        slug_by_item[item_key] = url_name
        if debug:
            print(f"[DEBUG] url_name for '{base_item_name}' = {url_name}")

    slugs_to_fetch = sorted({s for s in slug_by_item.values() if isinstance(s, str) and s and s not in p_cache})

    def _fetch_price(slug: str) -> Tuple[str, Optional[float]]:
        if max_workers > 1:
            worker_session = new_wfm_session(crossplay=crossplay)
            try:
                price = wfm_lowest_sell_price(
                    worker_session,
                    slug,
                    status_filter=status_filter,
                    timeout_s=timeout_s,
                    debug=debug,
                )
            finally:
                worker_session.close()
            return slug, price

        return slug, wfm_lowest_sell_price(
            session,
            slug,
            status_filter=status_filter,
            timeout_s=timeout_s,
            debug=debug,
        )

    if max_workers > 1 and len(slugs_to_fetch) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            for slug, price in ex.map(_fetch_price, slugs_to_fetch):
                p_cache[slug] = price
    else:
        for slug in slugs_to_fetch:
            _, price = _fetch_price(slug)
            p_cache[slug] = price
            if sleep_s > 0:
                time.sleep(sleep_s)

    for d in drops:
        base_item_name, item_qty = split_item_quantity(d.item_name)
        item_key = normalize_item_key(base_item_name)
        url_name = slug_by_item.get(item_key)
        price = p_cache.get(url_name) if isinstance(url_name, str) else None

        if price is None:
            price = DEFAULT_PRICE_BY_ITEM_KEY.get(item_key)
            if debug and price is not None:
                print(f"[DEBUG] fallback price for '{base_item_name}' = {price}")

        if price is not None and item_qty > 1:
            price = price * item_qty

        value = None
        if price is not None:
            value = (d.prob / 100.0) * price
            ev += value

        out.append(RelicDrop(item_name=d.item_name, rarity=d.rarity, prob=d.prob, price=price, value=value))

    if own_session:
        session.close()
    return out, ev


def print_report(relic_name: str, refinement: str, drops: List[RelicDrop], ev: float) -> None:
    relic_name = normalize_relic_name(relic_name)
    refinement = refinement.lower()

    print(f"Relic: {relic_name} | Refinement: {refinement}")
    print("-" * 90)
    print(f"{'Rarity':9} {'Prob%':>7} {'Price(p)':>10} {'EV':>10}  Item")
    print("-" * 90)

    order = {"rare": 0, "uncommon": 1, "common": 2}
    for d in sorted(drops, key=lambda x: (order.get(x.rarity, 99), x.item_name)):
        price_s = "N/A" if d.price is None else f"{d.price:.0f}"
        value_s = "N/A" if d.value is None else f"{d.value:.2f}"
        print(f"{d.rarity:9} {d.prob:7.2f} {price_s:>10} {value_s:>10}  {d.item_name}")

    print("-" * 90)
    print(f"Expected value (EV): {ev:.2f} platinum")


def main():
    ap = argparse.ArgumentParser(description="Warframe relic EV calculator (PC, lowest sell price from warframe.market)")
    ap.add_argument("relic", nargs="?", help='Relic name, e.g. "Lith A1"')
    ap.add_argument("--refinement", "-r", default="intact",
                    choices=["intact", "exceptional", "flawless", "radiant"])
    ap.add_argument("--static-relic-db", default=RELICS_DB_DEFAULT, help="Path to relics.json")
    ap.add_argument("--refresh-relic-db", action="store_true", help="Force refresh local relics.json before query")
    ap.add_argument("--refresh-only", action="store_true", help="Refresh local relics.json and exit")
    ap.add_argument("--status", default="ingame", choices=["ingame", "online", "any"],
                    help="Which seller status to consider for lowest sell price")
    ap.add_argument("--cache-path", default=CACHE_DEFAULT, help="Path to local items index cache JSON")
    ap.add_argument("--cache-ttl-hours", type=float, default=24.0, help="Items index cache TTL in hours")
    ap.add_argument("--timeout", type=float, default=12.0, help="HTTP timeout in seconds")
    ap.add_argument("--crossplay", default="true", choices=["true", "false"],
                    help="Crossplay header for WFM API requests")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.refresh_only:
        refresh_relics_db(path=args.static_relic_db, timeout_s=args.timeout, debug=args.debug)
        print(f"Relic DB refreshed: {args.static_relic_db}")
        return

    if args.refresh_relic_db:
        refresh_relics_db(path=args.static_relic_db, timeout_s=args.timeout, debug=args.debug)

    if not args.relic:
        ap.error("relic is required unless --refresh-only is used")

    drops = get_relic_drops_auto(
        args.relic,
        args.refinement,
        db_path=args.static_relic_db,
        timeout_s=args.timeout,
        debug=args.debug,
    )

    priced, ev = compute_prices_and_ev(
        drops,
        status_filter=args.status,
        debug=args.debug,
        cache_path=args.cache_path,
        cache_ttl_h=args.cache_ttl_hours,
        timeout_s=args.timeout,
        crossplay=(args.crossplay == "true"),
    )
    print_report(args.relic, args.refinement, priced, ev)


if __name__ == "__main__":
    main()