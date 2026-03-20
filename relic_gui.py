import threading
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from relic_ev import (
    ERA_DISPLAY_ALIASES,
    RELICS_DB_DEFAULT,
    compute_prices_and_ev,
    extract_relic_options,
    fetch_relic_titles_from_wiki,
    get_items_name_map_zh,
    get_relic_drops_auto,
    get_relic_vault_status_auto,
    load_relics_static,
    new_wfm_session,
    normalize_item_key,
    normalize_relic_name,
    refresh_relics_db,
)
from relic_ocr import OCRRelicHit, extract_relic_hits_from_clipboard, extract_relic_hits_from_image


class RelicEVGui:
    LANG_CHOICES = {
        "zh_CN": "简体中文",
        "en_US": "English",
    }
    REFINEMENT_ORDER = ["intact", "exceptional", "flawless", "radiant"]
    STATUS_ORDER = ["ingame", "online", "any"]
    I18N = {
        "zh_CN": {
            "title": "Warframe 遗物 EV 查询",
            "era": "时代:",
            "code": "核桃:",
            "manual": "或直接输入:",
            "refinement": "精炼:",
            "status": "卖家状态:",
            "query": "查询",
            "sync": "更新遗物库",
            "settings": "设置",
            "crossplay": "跨平台",
            "debug": "调试",
            "db_status": "遗物库",
            "db_syncing": "遗物库同步中...",
            "db_load_failed": "遗物库更新失败",
            "normalized": "标准名称",
            "ev": "总EV",
            "ev_loading": "总EV: 查询中...",
            "hint_input": "请输入遗物名，例如 中纪A9",
            "hint_title": "提示",
            "sync_failed": "更新失败",
            "sync_done_title": "完成",
            "sync_done_msg": "遗物库已更新",
            "query_failed": "查询失败",
            "settings_title": "设置",
            "language": "语言",
            "save": "保存",
            "cancel": "取消",
            "rarity": "稀有度",
            "prob": "概率%",
            "price": "价格(p)",
            "item": "掉落物",
            "na": "无",
            "common": "普通",
            "uncommon": "罕见",
            "rare": "稀有",
            "status_ingame": "游戏内",
            "status_online": "在线",
            "status_any": "任意",
            "ref_intact": "完好",
            "ref_exceptional": "优良",
            "ref_flawless": "无暇",
            "ref_radiant": "辉耀",
            "batch_input": "批量输入:",
            "batch_hint": "支持每行一个；也支持逗号/分号分隔",
            "batch_hint2": "支持数量后缀：中纪A6 x3",
            "batch_query": "批量查询",
            "sort_by": "排序:",
            "sort_input": "按给定列表顺序",
            "sort_value_desc": "按价值从高到低",
            "sort_value_asc": "按价值从低到高",
            "batch_relic": "遗物",
            "batch_common": "常见",
            "batch_uncommon": "罕见",
            "batch_rare": "传说",
            "batch_ev": "EV(p)",
            "batch_note": "说明",
            "vaulted": "入库",
            "active": "出库",
            "status_unknown": "未知",
            "batch_loading": "批量查询中...",
            "ocr_import": "识图导入",
            "ocr_clipboard": "识别剪贴板",
            "ocr_file_title": "选择截图",
            "ocr_done": "识别到 {count} 个遗物，开始批量查询",
            "ocr_preview": "识别到 {unique} 种遗物（总数量 {total}），已填入批量输入，请确认后点击批量查询",
            "ocr_preview_line": "{name} x{count}",
            "ocr_empty": "没有识别到遗物名称，请换更清晰的截图",
            "ocr_failed": "识图失败",
            "ocr_confidence": "OCR阈值",
            "ocr_conf_invalid": "OCR阈值需在 0~1 之间",
            "batch_workers": "批量并发",
            "batch_workers_invalid": "批量并发需为 1~32 的整数",
            "invalid_count_suffix": "数量格式无效: {line}",
            "tab_single": "单条查询",
            "tab_batch": "批量查询",
        },
        "en_US": {
            "title": "Warframe Relic EV",
            "era": "Era:",
            "code": "Relic:",
            "manual": "Or type:",
            "refinement": "Refinement:",
            "status": "Seller status:",
            "query": "Query",
            "sync": "Update Relic DB",
            "settings": "Settings",
            "crossplay": "Crossplay",
            "debug": "Debug",
            "db_status": "Relic DB",
            "db_syncing": "Relic DB syncing...",
            "db_load_failed": "Relic DB update failed",
            "normalized": "Normalized",
            "ev": "Total EV",
            "ev_loading": "Total EV: loading...",
            "hint_input": "Enter relic, e.g. Meso A9",
            "hint_title": "Hint",
            "sync_failed": "Update Failed",
            "sync_done_title": "Done",
            "sync_done_msg": "Relic DB updated",
            "query_failed": "Query Failed",
            "settings_title": "Settings",
            "language": "Language",
            "save": "Save",
            "cancel": "Cancel",
            "rarity": "Rarity",
            "prob": "Prob%",
            "price": "Price(p)",
            "item": "Drop",
            "na": "N/A",
            "common": "Common",
            "uncommon": "Uncommon",
            "rare": "Rare",
            "status_ingame": "In game",
            "status_online": "Online",
            "status_any": "Any",
            "ref_intact": "Intact",
            "ref_exceptional": "Exceptional",
            "ref_flawless": "Flawless",
            "ref_radiant": "Radiant",
            "batch_input": "Batch input:",
            "batch_hint": "One relic per line; comma/semicolon also supported",
            "batch_hint2": "Supports quantity suffix: Meso A6 x3",
            "batch_query": "Batch Query",
            "sort_by": "Sort:",
            "sort_input": "Given list order",
            "sort_value_desc": "EV high to low",
            "sort_value_asc": "EV low to high",
            "batch_relic": "Relic",
            "batch_common": "Common",
            "batch_uncommon": "Uncommon",
            "batch_rare": "Legendary",
            "batch_ev": "EV(p)",
            "batch_note": "Note",
            "vaulted": "Vaulted",
            "active": "Active",
            "status_unknown": "Unknown",
            "batch_loading": "Batch querying...",
            "ocr_import": "Image Import",
            "ocr_clipboard": "Clipboard OCR",
            "ocr_file_title": "Select screenshot",
            "ocr_done": "Detected {count} relics, starting batch query",
            "ocr_preview": "Detected {unique} relic types (total {total}), filled into batch input. Please confirm and click Batch Query",
            "ocr_preview_line": "{name} x{count}",
            "ocr_empty": "No relic names were detected",
            "ocr_failed": "Image OCR Failed",
            "ocr_confidence": "OCR threshold",
            "ocr_conf_invalid": "OCR threshold must be between 0 and 1",
            "batch_workers": "Batch workers",
            "batch_workers_invalid": "Batch workers must be an integer between 1 and 32",
            "invalid_count_suffix": "Invalid quantity suffix: {line}",
            "tab_single": "Single",
            "tab_batch": "Batch",
        },
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.geometry("980x680")
        self.root.minsize(760, 520)
        self.language_var = tk.StringVar(value="zh_CN")

        self.relic_var = tk.StringVar(value="中纪A9")
        self.era_var = tk.StringVar(value="中纪")
        self.code_var = tk.StringVar(value="")
        self.refinement_var = tk.StringVar(value="radiant")
        self.refinement_ui_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="ingame")
        self.status_ui_var = tk.StringVar(value="")
        self.crossplay_var = tk.BooleanVar(value=True)
        self.debug_var = tk.BooleanVar(value=False)
        self.ev_var = tk.StringVar(value="")
        self.normalized_name_var = tk.StringVar(value="")
        self.db_status_var = tk.StringVar(value="")
        self.batch_status_var = tk.StringVar(value="")
        self.sync_in_progress = False
        self.db_count = 0
        self.sort_mode_var = tk.StringVar(value="input")
        self.sort_mode_ui_var = tk.StringVar(value="")
        self.item_name_zh_map: Dict[str, str] = {}
        self.ocr_min_confidence = 0.45
        self.batch_max_workers = 8
        self.price_cache_ttl_s = 600.0
        self._price_cache_values: Dict[str, Optional[float]] = {}
        self._price_cache_expires_at: Dict[str, float] = {}
        self._price_cache_lock = threading.Lock()

        self.relic_options = {"Lith": [], "Meso": [], "Neo": [], "Axi": [], "Requiem": []}
        self.all_relic_names = []

        self.era_label: ttk.Label
        self.code_label: ttk.Label
        self.manual_label: ttk.Label
        self.refinement_label: ttk.Label
        self.status_label: ttk.Label
        self.query_btn: ttk.Button
        self.sync_btn: ttk.Button
        self.settings_btn: ttk.Button
        self.crossplay_chk: ttk.Checkbutton
        self.debug_chk: ttk.Checkbutton
        self.era_cb: ttk.Combobox
        self.code_cb: ttk.Combobox
        self.relic_entry: ttk.Entry
        self.refinement_cb: ttk.Combobox
        self.status_cb: ttk.Combobox
        self.suggest_list: tk.Listbox
        self.db_label: ttk.Label
        self.normalized_label: ttk.Label
        self.ev_label: ttk.Label
        self.table: ttk.Treeview
        self.batch_query_btn: ttk.Button
        self.ocr_btn: ttk.Button
        self.ocr_clip_btn: ttk.Button
        self.notebook: ttk.Notebook
        self.single_tab: ttk.Frame
        self.batch_tab: ttk.Frame
        self.sort_label: ttk.Label
        self.sort_cb: ttk.Combobox
        self.batch_input_label: ttk.Label
        self.batch_hint_label: ttk.Label
        self.batch_hint2_label: ttk.Label
        self.batch_text: tk.Text
        self.batch_table: ttk.Treeview
        self.batch_status_label: ttk.Label
        self._build_ui()
        self._apply_language_ui()
        self._load_relic_options(force_remote=False)
        # Auto refresh on startup using the same pipeline as manual sync.
        self.root.after(300, lambda: self._start_sync_db(show_dialog=False))

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)
        top.columnconfigure(5, weight=1)

        self.era_label = ttk.Label(top, text="")
        self.era_label.grid(row=0, column=0, sticky=tk.W)
        self.era_cb = ttk.Combobox(
            top,
            textvariable=self.era_var,
            values=[],
            width=8,
            state="readonly",
        )
        self.era_cb.grid(row=0, column=1, padx=(6, 12), sticky=tk.W)
        self.era_cb.bind("<<ComboboxSelected>>", self.on_era_change)

        self.code_label = ttk.Label(top, text="")
        self.code_label.grid(row=0, column=2, sticky=tk.W)
        self.code_cb = ttk.Combobox(top, textvariable=self.code_var, width=12, state="readonly")
        self.code_cb.grid(row=0, column=3, padx=(6, 12), sticky=tk.W)
        self.code_cb.bind("<<ComboboxSelected>>", self.on_code_change)

        self.manual_label = ttk.Label(top, text="")
        self.manual_label.grid(row=0, column=4, sticky=tk.W)
        self.relic_entry = ttk.Entry(top, textvariable=self.relic_var, width=18)
        self.relic_entry.grid(row=0, column=5, padx=(6, 12), sticky="we")
        self.relic_entry.bind("<KeyRelease>", self.on_relic_input_change)

        self.refinement_label = ttk.Label(top, text="")
        self.refinement_label.grid(row=1, column=0, sticky=tk.W)
        self.refinement_cb = ttk.Combobox(
            top,
            textvariable=self.refinement_ui_var,
            values=[],
            width=12,
            state="readonly",
        )
        self.refinement_cb.grid(row=1, column=1, padx=(6, 12), sticky=tk.W)
        self.refinement_cb.bind("<<ComboboxSelected>>", self.on_refinement_change)

        self.status_label = ttk.Label(top, text="")
        self.status_label.grid(row=1, column=2, sticky=tk.W)
        self.status_cb = ttk.Combobox(
            top,
            textvariable=self.status_ui_var,
            values=[],
            width=10,
            state="readonly",
        )
        self.status_cb.grid(row=1, column=3, padx=(6, 12), sticky=tk.W)
        self.status_cb.bind("<<ComboboxSelected>>", self.on_status_change)

        self.query_btn = ttk.Button(top, text="", command=self.on_query)
        self.query_btn.grid(row=1, column=4, padx=(6, 6), sticky=tk.W)

        self.sync_btn = ttk.Button(top, text="", command=self.on_sync_db)
        self.sync_btn.grid(row=1, column=5, padx=(0, 6), sticky=tk.W)

        self.settings_btn = ttk.Button(top, text="", command=self.on_open_settings)
        self.settings_btn.grid(row=1, column=6, padx=(0, 6), sticky=tk.W)

        self.suggest_list = tk.Listbox(top, height=6)
        self.suggest_list.grid(row=2, column=5, sticky="we", padx=(6, 12))
        self.suggest_list.grid_remove()
        self.suggest_list.bind("<<ListboxSelect>>", self.on_suggestion_pick)
        self.suggest_list.bind("<Double-1>", self.on_suggestion_pick)

        options = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        options.pack(fill=tk.X)
        self.crossplay_chk = ttk.Checkbutton(options, text="", variable=self.crossplay_var)
        self.crossplay_chk.pack(side=tk.LEFT)
        self.debug_chk = ttk.Checkbutton(options, text="", variable=self.debug_var)
        self.debug_chk.pack(side=tk.LEFT, padx=(16, 0))

        db_frame = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        db_frame.pack(fill=tk.X)
        self.db_label = ttk.Label(db_frame, textvariable=self.db_status_var)
        self.db_label.pack(side=tk.LEFT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.single_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.batch_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        self.notebook.add(self.single_tab, text="")
        self.notebook.add(self.batch_tab, text="")

        info = ttk.Frame(self.single_tab, padding=(0, 0, 0, 8))
        info.pack(fill=tk.X)
        self.normalized_label = ttk.Label(info, textvariable=self.normalized_name_var)
        self.normalized_label.pack(side=tk.LEFT)
        self.ev_label = ttk.Label(info, textvariable=self.ev_var)
        self.ev_label.pack(side=tk.RIGHT)

        table_frame = ttk.Frame(self.single_tab)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("rarity", "prob", "price", "ev", "item")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.table.heading("rarity", text="")
        self.table.heading("prob", text="")
        self.table.heading("price", text="")
        self.table.heading("ev", text="EV")
        self.table.heading("item", text="")
        self.table.column("rarity", width=90, anchor=tk.CENTER)
        self.table.column("prob", width=90, anchor=tk.E)
        self.table.column("price", width=90, anchor=tk.E)
        self.table.column("ev", width=90, anchor=tk.E)
        self.table.column("item", width=520, anchor=tk.W)

        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.table.tag_configure("vaulted", foreground="#C89B3C")
        self.table.tag_configure("active", foreground="#3A7BFF")
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        batch_actions = ttk.Frame(self.batch_tab, padding=(0, 0, 0, 8))
        batch_actions.pack(fill=tk.X)
        self.sort_label = ttk.Label(batch_actions, text="")
        self.sort_label.pack(side=tk.LEFT)
        self.sort_cb = ttk.Combobox(batch_actions, textvariable=self.sort_mode_ui_var, values=[], width=16, state="readonly")
        self.sort_cb.pack(side=tk.LEFT, padx=(6, 12))
        self.sort_cb.bind("<<ComboboxSelected>>", self.on_sort_mode_change)

        self.batch_query_btn = ttk.Button(batch_actions, text="", command=self.on_batch_query)
        self.batch_query_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.ocr_btn = ttk.Button(batch_actions, text="", command=self.on_import_image)
        self.ocr_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.ocr_clip_btn = ttk.Button(batch_actions, text="", command=self.on_import_clipboard)
        self.ocr_clip_btn.pack(side=tk.LEFT)

        batch_input = ttk.Frame(self.batch_tab, padding=(0, 0, 0, 8))
        batch_input.pack(fill=tk.X)
        self.batch_input_label = ttk.Label(batch_input, text="")
        self.batch_input_label.pack(anchor=tk.W)
        self.batch_text = tk.Text(batch_input, height=4, width=100)
        self.batch_text.pack(fill=tk.X, pady=(4, 0))
        self.batch_hint_label = ttk.Label(batch_input, text="")
        self.batch_hint_label.pack(anchor=tk.W, pady=(4, 0))
        self.batch_hint2_label = ttk.Label(batch_input, text="")
        self.batch_hint2_label.pack(anchor=tk.W)

        batch_status_frame = ttk.Frame(self.batch_tab, padding=(0, 0, 0, 8))
        batch_status_frame.pack(fill=tk.X)
        self.batch_status_label = ttk.Label(batch_status_frame, textvariable=self.batch_status_var)
        self.batch_status_label.pack(side=tk.LEFT)

        batch_table_frame = ttk.Frame(self.batch_tab)
        batch_table_frame.pack(fill=tk.BOTH, expand=True)

        batch_cols = ("relic", "common", "uncommon", "rare", "ev", "note")
        self.batch_table = ttk.Treeview(batch_table_frame, columns=batch_cols, show="headings")
        for c in batch_cols:
            self.batch_table.heading(c, text="")
        self.batch_table.column("relic", width=130, anchor=tk.W)
        self.batch_table.column("common", width=240, anchor=tk.W)
        self.batch_table.column("uncommon", width=190, anchor=tk.W)
        self.batch_table.column("rare", width=170, anchor=tk.W)
        self.batch_table.column("ev", width=90, anchor=tk.E)
        self.batch_table.column("note", width=160, anchor=tk.W)

        batch_scroll = ttk.Scrollbar(batch_table_frame, orient=tk.VERTICAL, command=self.batch_table.yview)
        self.batch_table.configure(yscrollcommand=batch_scroll.set)
        self.batch_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.batch_table.tag_configure("vaulted", foreground="#C89B3C")
        self.batch_table.tag_configure("active", foreground="#3A7BFF")
        batch_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _t(self, key: str) -> str:
        lang = self.language_var.get()
        return self.I18N.get(lang, self.I18N["zh_CN"]).get(key, key)

    def _display_refinement(self, code: str) -> str:
        return self._t(f"ref_{code}")

    def _display_status(self, code: str) -> str:
        return self._t(f"status_{code}")

    def _display_rarity(self, rarity: str) -> str:
        return self._t(rarity.lower())

    def _display_sort_mode(self, code: str) -> str:
        if code == "value_desc":
            return self._t("sort_value_desc")
        if code == "value_asc":
            return self._t("sort_value_asc")
        return self._t("sort_input")

    def _display_vault_status(self, code: str, with_emoji: bool = False) -> str:
        if code == "vaulted":
            label = self._t("vaulted")
            return f"🟡 {label}" if with_emoji else label
        if code == "active":
            label = self._t("active")
            return f"🔵 {label}" if with_emoji else label
        label = self._t("status_unknown")
        return f"⚪ {label}" if with_emoji else label

    def _snapshot_price_cache(self) -> Dict[str, Optional[float]]:
        now = time.time()
        with self._price_cache_lock:
            expired = [k for k, exp in self._price_cache_expires_at.items() if exp <= now]
            for k in expired:
                self._price_cache_expires_at.pop(k, None)
                self._price_cache_values.pop(k, None)
            return dict(self._price_cache_values)

    def _store_price_cache(self, latest_cache: Dict[str, Optional[float]]) -> None:
        if not latest_cache:
            return
        now = time.time()
        expire_at = now + self.price_cache_ttl_s
        with self._price_cache_lock:
            for slug, price in latest_cache.items():
                if not isinstance(slug, str) or not slug:
                    continue
                self._price_cache_values[slug] = price
                self._price_cache_expires_at[slug] = expire_at

    def _get_display_item_name(self, item_name: str) -> str:
        zh_name = self.item_name_zh_map.get(normalize_item_key(item_name))
        return zh_name if zh_name else item_name

    def _ensure_item_name_map(self) -> None:
        if self.item_name_zh_map:
            return
        try:
            session = new_wfm_session(crossplay=self.crossplay_var.get())
            self.item_name_zh_map = get_items_name_map_zh(session, debug=self.debug_var.get())
        except Exception:
            self.item_name_zh_map = {}

    def _update_db_status(self, error: Optional[str] = None) -> None:
        if error:
            self.db_status_var.set(f"{self._t('db_load_failed')}: {error}")
            return
        self.db_status_var.set(f"{self._t('db_status')}: {RELICS_DB_DEFAULT} ({self.db_count})")

    def _sync_display_vars_from_backend(self) -> None:
        self.refinement_ui_var.set(self._display_refinement(self.refinement_var.get()))
        self.status_ui_var.set(self._display_status(self.status_var.get()))
        self.sort_mode_ui_var.set(self._display_sort_mode(self.sort_mode_var.get()))

    def _apply_language_ui(self) -> None:
        self.root.title(self._t("title"))
        self.era_label.config(text=self._t("era"))
        self.code_label.config(text=self._t("code"))
        self.manual_label.config(text=self._t("manual"))
        self.refinement_label.config(text=self._t("refinement"))
        self.status_label.config(text=self._t("status"))
        self.query_btn.config(text=self._t("query"))
        self.batch_query_btn.config(text=self._t("batch_query"))
        self.ocr_btn.config(text=self._t("ocr_import"))
        self.ocr_clip_btn.config(text=self._t("ocr_clipboard"))
        self.sync_btn.config(text=self._t("sync"))
        self.settings_btn.config(text=self._t("settings"))
        self.sort_label.config(text=self._t("sort_by"))
        self.notebook.tab(0, text=self._t("tab_single"))
        self.notebook.tab(1, text=self._t("tab_batch"))
        self.batch_input_label.config(text=self._t("batch_input"))
        self.batch_hint_label.config(text=self._t("batch_hint"))
        self.batch_hint2_label.config(text=self._t("batch_hint2"))
        self.crossplay_chk.config(text=self._t("crossplay"))
        self.debug_chk.config(text=self._t("debug"))
        self.table.heading("rarity", text=self._t("rarity"))
        self.table.heading("prob", text=self._t("prob"))
        self.table.heading("price", text=self._t("price"))
        self.table.heading("item", text=self._t("item"))
        self.refinement_cb["values"] = [self._display_refinement(x) for x in self.REFINEMENT_ORDER]
        self.status_cb["values"] = [self._display_status(x) for x in self.STATUS_ORDER]
        sort_codes = ["input", "value_desc", "value_asc"]
        self.sort_cb["values"] = [self._display_sort_mode(x) for x in sort_codes]
        self._sync_display_vars_from_backend()
        self.era_cb["values"] = [self._display_era(x) for x in ["Lith", "Meso", "Neo", "Axi", "Requiem"]]
        self.normalized_name_var.set(f"{self._t('normalized')}: --")
        self.ev_var.set(f"{self._t('ev')}: --")
        self.batch_status_var.set("")
        self.batch_table.heading("relic", text=self._t("batch_relic"))
        self.batch_table.heading("common", text=self._t("batch_common"))
        self.batch_table.heading("uncommon", text=self._t("batch_uncommon"))
        self.batch_table.heading("rare", text=self._t("batch_rare"))
        self.batch_table.heading("ev", text=self._t("batch_ev"))
        self.batch_table.heading("note", text=self._t("batch_note"))
        self._update_db_status()

    def _canonical_era(self, display_era: str) -> str:
        if display_era in ("Lith", "Meso", "Neo", "Axi", "Requiem"):
            return display_era
        for canonical, labels in ERA_DISPLAY_ALIASES.items():
            if display_era in labels:
                return canonical
        return "Meso"

    def _display_era(self, canonical_era: str) -> str:
        if self.language_var.get() == "en_US":
            return canonical_era
        labels = ERA_DISPLAY_ALIASES.get(canonical_era, [])
        return labels[0] if labels else canonical_era

    def _set_code_values_for_era(self) -> None:
        era = self._canonical_era(self.era_var.get())
        codes = self.relic_options.get(era, [])
        self.code_cb["values"] = codes
        if codes and self.code_var.get() not in codes:
            self.code_var.set(codes[0])

    def _rebuild_all_relic_names(self) -> None:
        names = []
        for era, codes in self.relic_options.items():
            display_era = self._display_era(era)
            for c in codes:
                names.append(f"{era} {c}")
                names.append(f"{display_era}{c}")
        self.all_relic_names = sorted(set(names))

    def _load_relic_options(self, force_remote: bool = False) -> None:
        try:
            if force_remote:
                static_db = refresh_relics_db(path=RELICS_DB_DEFAULT, debug=self.debug_var.get())
            else:
                try:
                    static_db = load_relics_static(RELICS_DB_DEFAULT)
                except Exception:
                    static_db = refresh_relics_db(path=RELICS_DB_DEFAULT, debug=self.debug_var.get())

            # 本地库太小时，额外拉取 wiki 标题用于时代/核桃下拉候选。
            if len(static_db) < 50:
                try:
                    titles = fetch_relic_titles_from_wiki(debug=self.debug_var.get())
                    for t in titles:
                        static_db.setdefault(t, [])
                except Exception:
                    pass

            self.relic_options = extract_relic_options(static_db)
            self.db_count = len(static_db)
            self._set_code_values_for_era()
            self._rebuild_all_relic_names()
            self._update_db_status()
        except Exception as e:
            self._update_db_status(error=str(e))

    def on_era_change(self, _event=None) -> None:
        self._set_code_values_for_era()
        self.on_code_change()

    def on_code_change(self, _event=None) -> None:
        code = self.code_var.get().strip()
        if code:
            self.relic_var.set(f"{self.era_var.get()}{code}")

    def on_relic_input_change(self, _event=None) -> None:
        q = self.relic_var.get().strip().lower()
        if not q:
            self.suggest_list.grid_remove()
            return

        q_compact = q.replace(" ", "")
        matches = []
        for name in self.all_relic_names:
            n = name.lower()
            if q in n or q_compact in n.replace(" ", ""):
                matches.append(name)
            if len(matches) >= 15:
                break

        if not matches:
            self.suggest_list.grid_remove()
            return

        self.suggest_list.delete(0, tk.END)
        for m in matches:
            self.suggest_list.insert(tk.END, m)
        self.suggest_list.grid()

    def on_suggestion_pick(self, _event=None) -> None:
        sel = self.suggest_list.curselection()
        if not sel:
            return
        choice = self.suggest_list.get(sel[0])
        self.relic_var.set(choice)
        self.suggest_list.grid_remove()
        try:
            normalized = normalize_relic_name(choice)
            parts = normalized.split()
            if len(parts) >= 2:
                self.era_var.set(self._display_era(parts[0]))
                self._set_code_values_for_era()
                self.code_var.set(" ".join(parts[1:]))
        except Exception:
            pass

    def on_refinement_change(self, _event=None) -> None:
        selected = self.refinement_ui_var.get()
        for code in self.REFINEMENT_ORDER:
            if self._display_refinement(code) == selected:
                self.refinement_var.set(code)
                return

    def on_status_change(self, _event=None) -> None:
        selected = self.status_ui_var.get()
        for code in self.STATUS_ORDER:
            if self._display_status(code) == selected:
                self.status_var.set(code)
                return

    def on_sort_mode_change(self, _event=None) -> None:
        selected = self.sort_mode_ui_var.get()
        for code in ("input", "value_desc", "value_asc"):
            if self._display_sort_mode(code) == selected:
                self.sort_mode_var.set(code)
                return

    def on_open_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title(self._t("settings_title"))
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"{self._t('language')}: ").grid(row=0, column=0, sticky=tk.W)
        lang_ui_var = tk.StringVar(value=self.LANG_CHOICES.get(self.language_var.get(), "简体中文"))
        lang_cb = ttk.Combobox(
            frame,
            textvariable=lang_ui_var,
            values=list(self.LANG_CHOICES.values()),
            state="readonly",
            width=14,
        )
        lang_cb.grid(row=0, column=1, padx=(8, 0), sticky=tk.W)

        ttk.Label(frame, text=f"{self._t('ocr_confidence')}: ").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        conf_var = tk.StringVar(value=f"{self.ocr_min_confidence:.2f}")
        conf_entry = ttk.Entry(frame, textvariable=conf_var, width=8)
        conf_entry.grid(row=1, column=1, padx=(8, 0), sticky=tk.W, pady=(8, 0))

        ttk.Label(frame, text=f"{self._t('batch_workers')}: ").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        workers_var = tk.StringVar(value=str(self.batch_max_workers))
        workers_entry = ttk.Entry(frame, textvariable=workers_var, width=8)
        workers_entry.grid(row=2, column=1, padx=(8, 0), sticky=tk.W, pady=(8, 0))

        btns = ttk.Frame(frame)
        btns.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky=tk.E)

        def save_settings() -> None:
            selected_ui = lang_ui_var.get()
            selected_lang = "zh_CN"
            for k, v in self.LANG_CHOICES.items():
                if v == selected_ui:
                    selected_lang = k
                    break
            self.language_var.set(selected_lang)
            try:
                conf = float(conf_var.get().strip())
            except Exception:
                messagebox.showwarning(self._t("hint_title"), self._t("ocr_conf_invalid"))
                return
            if conf < 0.0 or conf > 1.0:
                messagebox.showwarning(self._t("hint_title"), self._t("ocr_conf_invalid"))
                return

            try:
                workers = int(workers_var.get().strip())
            except Exception:
                messagebox.showwarning(self._t("hint_title"), self._t("batch_workers_invalid"))
                return
            if workers < 1 or workers > 32:
                messagebox.showwarning(self._t("hint_title"), self._t("batch_workers_invalid"))
                return

            self.ocr_min_confidence = conf
            self.batch_max_workers = workers
            self._apply_language_ui()
            self._set_code_values_for_era()
            self._rebuild_all_relic_names()
            win.destroy()

        ttk.Button(btns, text=self._t("save"), command=save_settings).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btns, text=self._t("cancel"), command=win.destroy).pack(side=tk.LEFT)

    def on_sync_db(self) -> None:
        self._start_sync_db(show_dialog=True)

    def _start_sync_db(self, show_dialog: bool) -> None:
        if self.sync_in_progress:
            return
        self.sync_in_progress = True
        self.sync_btn.config(state=tk.DISABLED)
        self.db_status_var.set(self._t("db_syncing"))
        worker = threading.Thread(target=self._sync_worker, args=(show_dialog,), daemon=True)
        worker.start()

    def _sync_worker(self, show_dialog: bool) -> None:
        try:
            refresh_relics_db(path=RELICS_DB_DEFAULT, debug=self.debug_var.get())
            self.root.after(0, lambda: self._on_sync_done(None, show_dialog))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._on_sync_done(e, show_dialog))

    def _on_sync_done(self, exc: Exception, show_dialog: bool) -> None:
        self.sync_in_progress = False
        self.sync_btn.config(state=tk.NORMAL)
        self._load_relic_options(force_remote=False)
        if exc:
            if show_dialog:
                messagebox.showerror(self._t("sync_failed"), str(exc))
            else:
                self._update_db_status(error=str(exc))
            return
        if show_dialog:
            messagebox.showinfo(self._t("sync_done_title"), self._t("sync_done_msg"))

    def on_query(self) -> None:
        relic_input = self.relic_var.get().strip()
        if not relic_input and self.code_var.get().strip():
            relic_input = f"{self.era_var.get()}{self.code_var.get().strip()}"
        if not relic_input:
            messagebox.showwarning(self._t("hint_title"), self._t("hint_input"))
            return

        self.query_btn.config(state=tk.DISABLED)
        self.ev_var.set(self._t("ev_loading"))

        # 网络请求放到后台线程，避免界面卡死。
        worker = threading.Thread(
            target=self._query_worker,
            args=(relic_input,),
            daemon=True,
        )
        worker.start()

    def _parse_batch_inputs(self) -> List[Dict[str, Any]]:
        raw = self.batch_text.get("1.0", tk.END).strip()
        if not raw:
            return []
        for sep in [",", "，", ";", "；", "\t"]:
            raw = raw.replace(sep, "\n")
        rows = [x.strip() for x in raw.splitlines() if x.strip()]

        merged: Dict[str, Dict[str, Any]] = {}
        out: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            line = row
            count = 1

            m = re.search(r"^(.*?)(?:\s*[xX×*＊]\s*(\d+))$", line)
            if m:
                line = m.group(1).strip()
                try:
                    count = max(1, int(m.group(2)))
                except Exception:
                    out.append({"index": idx, "relic": row, "count": 1, "normalized": None})
                    continue

            try:
                normalized = normalize_relic_name(line)
                key = normalized.lower()
                if key not in merged:
                    merged[key] = {
                        "index": idx,
                        "relic": normalized,
                        "count": count,
                        "normalized": normalized,
                    }
                else:
                    merged[key]["count"] += count
            except Exception:
                out.append({"index": idx, "relic": row, "count": count, "normalized": None})

        out.extend(merged.values())
        out.sort(key=lambda x: x.get("index", 0))
        return out

    def on_batch_query(self) -> None:
        relic_entries = self._parse_batch_inputs()
        if not relic_entries:
            messagebox.showwarning(self._t("hint_title"), self._t("hint_input"))
            return

        self._set_action_buttons(enabled=False)
        self.batch_status_var.set(self._t("batch_loading"))

        worker = threading.Thread(
            target=self._batch_query_worker,
            args=(relic_entries,),
            daemon=True,
        )
        worker.start()

    def on_import_image(self) -> None:
        path = filedialog.askopenfilename(
            title=self._t("ocr_file_title"),
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        self._set_action_buttons(enabled=False)
        self.batch_status_var.set(self._t("batch_loading"))

        worker = threading.Thread(
            target=self._ocr_worker,
            args=("file", path),
            daemon=True,
        )
        worker.start()

    def on_import_clipboard(self) -> None:
        self._set_action_buttons(enabled=False)
        self.batch_status_var.set(self._t("batch_loading"))

        worker = threading.Thread(
            target=self._ocr_worker,
            args=("clipboard", None),
            daemon=True,
        )
        worker.start()

    def _ocr_worker(self, source: str, image_path: Optional[str]) -> None:
        try:
            if source == "clipboard":
                hits = extract_relic_hits_from_clipboard(
                    min_confidence=self.ocr_min_confidence,
                    debug=self.debug_var.get(),
                )
            else:
                hits = extract_relic_hits_from_image(
                    image_path or "",
                    min_confidence=self.ocr_min_confidence,
                    debug=self.debug_var.get(),
                )
            self.root.after(0, lambda: self._on_ocr_done(hits))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._on_ocr_failed(e))

    def _on_ocr_done(self, hits: List[OCRRelicHit]) -> None:
        self._set_action_buttons(enabled=True)

        if not hits:
            self.batch_status_var.set("")
            messagebox.showwarning(self._t("hint_title"), self._t("ocr_empty"))
            return

        lines = [
            self._t("ocr_preview_line").format(name=h.name, count=h.count)
            for h in hits
        ]
        self.batch_text.delete("1.0", tk.END)
        self.batch_text.insert("1.0", "\n".join(lines))
        total_count = sum(h.count for h in hits)
        self.batch_status_var.set(self._t("ocr_preview").format(unique=len(hits), total=total_count))

    def _on_ocr_failed(self, exc: Exception) -> None:
        self._set_action_buttons(enabled=True)
        self.batch_status_var.set("")
        messagebox.showerror(self._t("ocr_failed"), str(exc))

    def _batch_query_worker(self, relic_entries: List[Dict[str, Any]]) -> None:
        rows: List[Dict[str, Any]] = []
        self._ensure_item_name_map()
        session = new_wfm_session(crossplay=self.crossplay_var.get())
        item_slug_cache: Dict[str, Optional[str]] = {}
        price_cache = self._snapshot_price_cache()
        item_index: Dict[str, str] = {}
        for entry in relic_entries:
            idx = int(entry.get("index", 0))
            count = int(entry.get("count", 1))
            normalized = entry.get("normalized")
            relic_input = str(entry.get("relic", "")).strip()
            try:
                if not normalized:
                    raise ValueError(f"无法识别遗物名: {relic_input}")
                drops = get_relic_drops_auto(
                    normalized,
                    self.refinement_var.get(),
                    db_path=RELICS_DB_DEFAULT,
                    debug=self.debug_var.get(),
                )
                priced, ev = compute_prices_and_ev(
                    drops,
                    status_filter=self.status_var.get(),
                    debug=self.debug_var.get(),
                    crossplay=self.crossplay_var.get(),
                    sleep_s=0.0,
                    session=session,
                    item_slug_cache=item_slug_cache,
                    price_cache=price_cache,
                    shared_item_index=item_index,
                    max_workers=self.batch_max_workers,
                )
                by_rarity: Dict[str, List[str]] = {"common": [], "uncommon": [], "rare": []}
                for d in priced:
                    item_name = self._get_display_item_name(d.item_name)
                    price_text = self._t("na") if d.price is None else f"{d.price:.0f}p"
                    by_rarity.setdefault(d.rarity, []).append(f"{item_name} ({price_text})")

                vault_status = get_relic_vault_status_auto(normalized, db_path=RELICS_DB_DEFAULT, debug=self.debug_var.get())

                rows.append({
                    "index": idx,
                    "relic": normalized,
                    "count": count,
                    "common": " / ".join(by_rarity.get("common", [])),
                    "uncommon": " / ".join(by_rarity.get("uncommon", [])),
                    "rare": " / ".join(by_rarity.get("rare", [])),
                    "ev": ev,
                    "note": self._display_vault_status(vault_status, with_emoji=True),
                    "vault_status": vault_status,
                })
            except Exception as exc:
                rows.append({
                    "index": idx,
                    "relic": relic_input,
                    "count": count,
                    "common": "--",
                    "uncommon": "--",
                    "rare": "--",
                    "ev": None,
                    "note": str(exc),
                    "vault_status": "unknown",
                })

        session.close()
        self._store_price_cache(price_cache)
        self.root.after(0, lambda: self._show_batch_result(rows))
        self.root.after(0, lambda: self._load_relic_options(force_remote=False))

    def _show_batch_result(self, rows: List[Dict[str, Any]]) -> None:
        for row_id in self.batch_table.get_children():
            self.batch_table.delete(row_id)

        mode = self.sort_mode_var.get()
        if mode == "value_desc":
            rows = sorted(rows, key=lambda r: (r.get("ev") is None, -(r.get("ev") or 0.0), r.get("index", 0)))
        elif mode == "value_asc":
            rows = sorted(rows, key=lambda r: (r.get("ev") is None, (r.get("ev") or 0.0), r.get("index", 0)))
        else:
            rows = sorted(rows, key=lambda r: r.get("index", 0))

        for r in rows:
            ev = r.get("ev")
            ev_text = self._t("na") if ev is None else f"{ev:.2f}"
            relic_text = str(r.get("relic", ""))
            count = int(r.get("count", 1) or 1)
            if count > 1:
                relic_text = f"{relic_text} x{count}"
            row_status = r.get("vault_status")
            tags = (row_status,) if row_status in ("vaulted", "active") else ()
            self.batch_table.insert(
                "",
                tk.END,
                values=(
                    relic_text,
                    r.get("common", ""),
                    r.get("uncommon", ""),
                    r.get("rare", ""),
                    ev_text,
                    r.get("note", ""),
                ),
                tags=tags,
            )

        ok_count = sum(1 for r in rows if r.get("ev") is not None)
        self.batch_status_var.set(f"{ok_count}/{len(rows)}")
        self._set_action_buttons(enabled=True)

    def _query_worker(self, relic_input: str) -> None:
        try:
            normalized = normalize_relic_name(relic_input)
            drops = get_relic_drops_auto(
                normalized,
                self.refinement_var.get(),
                db_path=RELICS_DB_DEFAULT,
                debug=self.debug_var.get(),
            )
            price_cache = self._snapshot_price_cache()
            priced, ev = compute_prices_and_ev(
                drops,
                status_filter=self.status_var.get(),
                debug=self.debug_var.get(),
                crossplay=self.crossplay_var.get(),
                sleep_s=0.0,
                price_cache=price_cache,
                max_workers=6,
            )
            self._store_price_cache(price_cache)
            vault_status = get_relic_vault_status_auto(normalized, db_path=RELICS_DB_DEFAULT, debug=self.debug_var.get())
            self._ensure_item_name_map()
            for d in priced:
                d.item_name = self._get_display_item_name(d.item_name)
            self.root.after(0, lambda: self._show_result(normalized, priced, ev, vault_status))
            self.root.after(0, lambda: self._load_relic_options(force_remote=False))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._show_error(e))

    def _show_result(self, relic_name: str, drops, ev: float, vault_status: str = "unknown") -> None:
        for row in self.table.get_children():
            self.table.delete(row)

        order = {"rare": 0, "uncommon": 1, "common": 2}
        row_tag = vault_status if vault_status in ("vaulted", "active") else ""
        for d in sorted(drops, key=lambda x: (order.get(x.rarity, 99), x.item_name)):
            price_s = self._t("na") if d.price is None else f"{d.price:.0f}"
            ev_s = self._t("na") if d.value is None else f"{d.value:.2f}"
            item_label = f"{d.item_name} ({price_s}p)"
            self.table.insert(
                "",
                tk.END,
                values=(self._display_rarity(d.rarity), f"{d.prob:.2f}", price_s, ev_s, item_label),
                tags=((row_tag,) if row_tag else ()),
            )

        status_text = self._display_vault_status(vault_status)
        self.normalized_name_var.set(f"{self._t('normalized')}: {relic_name} ({status_text})")
        self.ev_var.set(f"{self._t('ev')}: {ev:.2f} p")
        self.query_btn.config(state=tk.NORMAL)

    def _show_error(self, exc: Exception) -> None:
        self._set_action_buttons(enabled=True)
        self.ev_var.set(f"{self._t('ev')}: --")
        messagebox.showerror(self._t("query_failed"), str(exc))

    def _set_action_buttons(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.query_btn.config(state=state)
        self.batch_query_btn.config(state=state)
        self.ocr_btn.config(state=state)
        self.ocr_clip_btn.config(state=state)


def main() -> None:
    root = tk.Tk()
    RelicEVGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

