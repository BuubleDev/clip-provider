import csv
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import json
import html
import hashlib
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE = Path(__file__).resolve().parent.parent
APP_DIR = BASE / "app"
VENDOR_DIR = APP_DIR / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

try:
    from ddgs import DDGS
except Exception:
    DDGS = None

try:
    import requests
    from playwright.sync_api import sync_playwright
except Exception:
    requests = None
    sync_playwright = None

QUEUE_FILE = BASE / "video_queue.tsv"
HISTORY_FILE = BASE / "download_history.tsv"
LOG_FILE = BASE / "activity.log"
KEYWORDS_FILE = BASE / "BEAUTY_SEARCH_KEYWORDS.txt"
IMAGE_SEARCH_DIR = BASE / "Image_Search"
EDITED_DIR = BASE / "Edited"
REJECTED_DIR = BASE / "Rejected_Low_Resolution"
REJECTED_SHORT_DIR = BASE / "Rejected_Too_Short"
PROCESSING_DIR = EDITED_DIR / "Processing"
READY_DIR = EDITED_DIR / "Ready"
NEEDS_REVIEW_DIR = EDITED_DIR / "Needs_Review"
NEEDS_TRIM_DIR = EDITED_DIR / "Needs_Trim"
REVIEWED_SOURCE_DIR = EDITED_DIR / "Reviewed_Sources"
STOCKOS_PENDING_DIR = EDITED_DIR / "StockOS_Pending"
SENT_STOCKOS_DIR = EDITED_DIR / "Sent_to_StockOS"
SENT_SOURCE_DIR = SENT_STOCKOS_DIR / "Reviewed_Sources"
MUSIC_ROOT = BASE / "Song"
MUSIC_DIRS = (MUSIC_ROOT / "Reels" / "_Cuts", MUSIC_ROOT / "Reels_Cuts")
SCHEDULE_PLAN_FILE = BASE / "stockos_schedule_plan.tsv"
PLATFORM_DIRS = {
    "Douyin": BASE / "douyin",
    "Xiaohongshu": BASE / "Xiaohongshu",
    "Bilibili": BASE / "Billibili",
}
SEARCH_DOMAINS = {
    "Douyin": "douyin.com/video",
    "Xiaohongshu": "xiaohongshu.com/explore",
    "Bilibili": "bilibili.com/video",
}
PRODUCT_CATEGORIES = {
    "กิ๊บ (Hair Clips)": {
        "folder": "Hair_Clips",
        "keywords": ("抓夹", "发夹", "鲨鱼夹", "边夹", "刘海夹", "claw clip", "hair clip", "กิ๊บ"),
        "search": "抓夹 发夹 发型教程",
    },
    "ที่รัดผม (Hair Bands)": {
        "folder": "Hair_Bands",
        "keywords": ("发带", "头带", "发圈", "皮筋", "头绳", "scrunchie", "hair band", "headband", "ที่รัดผม", "ยางรัดผม"),
        "search": "发带 发圈 发型教程",
    },
    "ต่างหู (Earrings)": {
        "folder": "Earrings",
        "keywords": ("耳环", "耳钉", "耳饰", "earring", "ต่างหู"),
        "search": "耳环 耳钉 佩戴教程",
    },
    "แต่งหน้า (Makeup)": {
        "folder": "Makeup",
        "keywords": ("化妆", "彩妆", "眼影", "口红", "粉底", "makeup", "แต่งหน้า"),
        "search": "化妆 彩妆 教程",
    },
    "ทาเล็บ (Nails)": {
        "folder": "Nails",
        "keywords": ("美甲", "指甲油", "涂指甲", "nail polish", "manicure", "ทาเล็บ", "เล็บ"),
        "search": "美甲 指甲油 教程",
    },
    "สิว/สกินแคร์ (Skincare)": {
        "folder": "Skincare",
        "keywords": ("祛痘", "挤痘", "粉刺", "护肤", "面膜", "去角质", "skincare", "acne", "กดสิว", "ลอกหน้า"),
        "search": "护肤 祛痘 粉刺 教程",
    },
    "เล็บขบ/ดูแลเล็บ (Nail Care)": {
        "folder": "Nail_Care",
        "keywords": ("嵌甲", "甲沟炎", "修脚", "ingrown nail", "ตัดเล็บขบ", "เล็บขบ"),
        "search": "嵌甲 甲沟炎 修脚 教程",
    },
    "อื่นๆ (Other)": {
        "folder": "Other",
        "keywords": (),
        "search": "美容 教程",
    },
}
CATEGORY_OPTIONS = ("Auto", *PRODUCT_CATEGORIES.keys())
TUTORIAL_TERMS = ("教程", "用法", "步骤", "发型", "盘发", "抓夹", "鲨鱼夹", "发夹", "tutorial", "how to")
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ensure_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    for path in (EDITED_DIR, REJECTED_DIR, REJECTED_SHORT_DIR, PROCESSING_DIR, IMAGE_SEARCH_DIR,
                 READY_DIR, NEEDS_REVIEW_DIR, NEEDS_TRIM_DIR, REVIEWED_SOURCE_DIR, STOCKOS_PENDING_DIR,
                 SENT_STOCKOS_DIR, SENT_SOURCE_DIR, MUSIC_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    for path in PLATFORM_DIRS.values():
        path.mkdir(parents=True, exist_ok=True)
        for config in PRODUCT_CATEGORIES.values():
            (path / config["folder"]).mkdir(parents=True, exist_ok=True)


def safe_name(text):
    cleaned = "".join(c if c.isalnum() or c in " ._-[]()" else "_" for c in text)
    return " ".join(cleaned.split())[:120] or "video"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Hair Tutorial Collector")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{min(1360, max(950, screen_width - 80))}x{min(850, max(620, screen_height - 100))}")
        self.root.minsize(950, 620)
        self.events = queue.Queue()
        self.stop_watch = threading.Event()
        self.batch_active = threading.Event()
        self.cleaning_active = threading.Event()
        self.music_cutting_active = threading.Event()
        self.queue_file_lock = threading.Lock()
        self.download_gate = threading.Event()
        self.download_gate.set()
        self.stop_after_current = threading.Event()
        self.last_opened_url = ""
        self.platform_vars = {name: tk.BooleanVar(value=True) for name in PLATFORM_DIRS}
        self.use_cookies = tk.BooleanVar(value=False)
        self.auto_download = tk.BooleanVar(value=True)
        self.parallel_platforms = tk.BooleanVar(value=True)
        self.keyword = tk.StringVar(value="抓夹发型教程")
        self.product_category = tk.StringVar(value="Auto")
        self.target_count = tk.IntVar(value=20)
        self.min_short_edge = tk.IntVar(value=720)
        self.min_duration = tk.IntVar(value=8)
        self.max_duration = tk.IntVar(value=45)
        self.auto_prepare = tk.BooleanVar(value=True)
        self.mute_audio = tk.BooleanVar(value=True)
        self.mute_original_audio = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready")
        self.summary = tk.StringVar(value="Queue: 0")
        self.progress_text = tk.StringVar(value="Idle")
        self.brand_text = tk.StringVar(value="BUUBLE.VBG | Hair Ideas")
        self.brand_website = tk.StringVar(value="buublestore.com")
        self.brand_position = tk.StringVar(value="bottom-right")
        self.english_headline = tk.StringVar(value="Easy Claw Clip Tutorial")
        self.text_mode = tk.StringVar(value="Remove OCR + English Text")
        self.stockos_connector = None
        self.stockos_init_error = None
        try:
            from stockos_connector import StockOSConnector
            self.stockos_connector = StockOSConnector(BASE)
        except Exception as exc:
            self.stockos_init_error = str(exc)
        # Review is intentionally required by default. Auto-send remains an
        # explicit opt-in for advanced use and never inherits a previous run.
        self.stockos_auto = tk.BooleanVar(value=False)
        self.stockos_status = tk.StringVar(value="Not configured")
        self.music_status = tk.StringVar(value="Music: checking library...")
        self.last_music_path = None
        self.last_image_search_path = None
        self.full_queue_window = None
        self.full_queue_tree = None
        self.stockos_upload_queue = queue.Queue()
        self.stockos_enqueued = set()
        self.stockos_enqueued_lock = threading.Lock()
        self.pipeline_lock = threading.Lock()
        self.build_ui()
        self.refresh_music_status()
        self.load_queue()
        threading.Thread(target=self.stockos_upload_worker, daemon=True).start()
        if self.stockos_connector and self.stockos_connector.configured():
            self.stockos_status.set("Connected — review Ready clips before sending")
        elif self.stockos_init_error:
            self.emit(f"StockOS connector unavailable: {self.stockos_init_error}")
        self.root.after(200, self.flush_events)

    def build_ui(self):
        notebook = ttk.Notebook(self.root, height=250)
        notebook.pack(fill="x", padx=10, pady=(8, 0))
        find_tab = ttk.Frame(notebook)
        edit_tab = ttk.Frame(notebook)
        publish_tab = ttk.Frame(notebook)
        notebook.add(find_tab, text="Find & download")
        notebook.add(edit_tab, text="Edit & review")
        notebook.add(publish_tab, text="Music & StockOS")

        top = ttk.Frame(find_tab, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Platform:").pack(side="left")
        for name in PLATFORM_DIRS:
            ttk.Checkbutton(top, text=name, variable=self.platform_vars[name]).pack(side="left", padx=8)
        ttk.Label(top, text="Minimum quality:").pack(side="left", padx=(18, 3))
        ttk.Spinbox(top, from_=480, to=2160, increment=120, textvariable=self.min_short_edge, width=5).pack(side="left")
        ttk.Label(top, text="px short edge (720p)").pack(side="left", padx=3)
        ttk.Checkbutton(top, text="Try Chrome cookies", variable=self.use_cookies).pack(side="right")

        research = ttk.LabelFrame(find_tab, text="Automatic research", padding=8)
        research.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(research, text="Topic / keywords:").pack(side="left")
        ttk.Entry(research, textvariable=self.keyword, width=35).pack(side="left", padx=5)
        ttk.Label(research, text="Target per platform:").pack(side="left")
        ttk.Spinbox(research, from_=1, to=100, textvariable=self.target_count, width=5).pack(side="left", padx=5)
        ttk.Checkbutton(research, text="Download after finding", variable=self.auto_download).pack(side="left", padx=8)
        ttk.Checkbutton(research, text="Parallel platforms", variable=self.parallel_platforms).pack(side="left", padx=5)
        ttk.Button(research, text="AUTO FIND & DOWNLOAD", command=self.auto_find).pack(side="right")
        ttk.Button(research, text="Keyword list", command=self.open_keyword_list).pack(side="right", padx=5)

        special = ttk.Frame(find_tab, padding=(10, 0, 10, 8))
        special.pack(fill="x")
        ttk.Button(special, text="Search REDnote / Xiaohongshu", command=self.search_xhs_browser).pack(side="left", padx=3)
        ttk.Button(special, text="SEARCH BY PRODUCT IMAGE", command=self.image_search_helper).pack(side="left", padx=3)
        ttk.Label(special, text="Category:").pack(side="left", padx=(12, 3))
        ttk.Combobox(
            special,
            textvariable=self.product_category,
            state="readonly",
            width=25,
            values=CATEGORY_OPTIONS,
        ).pack(side="left", padx=3)
        ttk.Label(special, text="Auto detects a download folder from the keyword.").pack(side="left", padx=10)

        editing = ttk.LabelFrame(edit_tab, text="English branded copy (keeps originals)", padding=6)
        editing.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(editing, text="Brand:").pack(side="left")
        ttk.Entry(editing, textvariable=self.brand_text, width=28).pack(side="left", padx=4)
        ttk.Label(editing, text="Website:").pack(side="left")
        ttk.Entry(editing, textvariable=self.brand_website, width=22).pack(side="left", padx=4)
        ttk.Combobox(editing, textvariable=self.brand_position, state="readonly", width=12,
                     values=("top-left", "top-right", "bottom-left", "bottom-right")).pack(side="left", padx=4)
        ttk.Button(editing, text="BRAND COPY (FAST)", command=self.brand_video_dialog).pack(side="right", padx=3)
        ttk.Button(editing, text="REMOVE TEXT + BRAND", command=self.clean_video_dialog).pack(side="right", padx=3)

        covering = ttk.Frame(edit_tab, padding=(10, 0, 10, 8))
        covering.pack(fill="x")
        ttk.Label(covering, text="English cover text:").pack(side="left")
        ttk.Entry(covering, textvariable=self.english_headline, width=28).pack(side="left", padx=5)
        ttk.Button(covering, text="COVER + ENGLISH", command=self.cover_video_dialog).pack(side="left", padx=3)
        ttk.Button(covering, text="REMOVE + ENGLISH", command=self.text_only_video_dialog).pack(side="left", padx=3)
        ttk.Label(covering, text="Automatic text mode:").pack(side="left", padx=(18, 3))
        ttk.Combobox(covering, textvariable=self.text_mode, state="readonly", width=27,
                     values=("Remove OCR + English Text", "Cover with English", "Remove with OCR")).pack(side="left", padx=3)

        pipeline = ttk.LabelFrame(edit_tab, text="Automatic publishing preparation", padding=6)
        pipeline.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(pipeline, text="Duration:").pack(side="left")
        ttk.Spinbox(pipeline, from_=1, to=180, textvariable=self.min_duration, width=4).pack(side="left", padx=(3, 1))
        ttk.Label(pipeline, text="to").pack(side="left")
        ttk.Spinbox(pipeline, from_=2, to=300, textvariable=self.max_duration, width=4).pack(side="left", padx=3)
        ttk.Label(pipeline, text="seconds").pack(side="left")
        ttk.Checkbutton(pipeline, text="Auto remove text + brand after download (slow)",
                        variable=self.auto_prepare).pack(side="left", padx=12)
        ttk.Checkbutton(pipeline, text="Mute edited copies", variable=self.mute_audio).pack(side="left", padx=5)
        ttk.Checkbutton(pipeline, text="Mute downloaded originals too",
                        variable=self.mute_original_audio).pack(side="left", padx=5)
        ttk.Button(pipeline, text="Dashboard", command=self.show_dashboard).pack(side="right", padx=3)
        ttk.Button(pipeline, text="Open Ready", command=self.open_ready_folder).pack(side="right", padx=3)

        review_flow = ttk.LabelFrame(edit_tab, text="Needs Review / Needs Trim workflow", padding=6)
        review_flow.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(
            review_flow,
            text="After fixing a clip: process it again, or approve it directly. Ready movement is automatic.",
        ).pack(side="left", padx=4)
        ttk.Button(review_flow, text="Open Review", command=self.open_needs_review_folder).pack(side="right", padx=3)
        ttk.Button(review_flow, text="Open Trim", command=self.open_needs_trim_folder).pack(side="right", padx=3)
        ttk.Button(review_flow, text="APPROVE FIXED → READY", command=self.approve_fixed_dialog).pack(side="right", padx=3)
        ttk.Button(review_flow, text="PROCESS SELECTED MODE → READY", command=self.process_fixed_dialog).pack(side="right", padx=3)

        music = ttk.LabelFrame(publish_tab, text="Music — added only after Ready review", padding=6)
        music.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(music, textvariable=self.music_status).pack(side="left", padx=4)
        ttk.Label(music, text="Random track · source audio replaced · volume 24%").pack(side="left", padx=12)
        ttk.Button(music, text="Refresh music", command=self.refresh_music_status).pack(side="right", padx=3)
        ttk.Button(music, text="Cut songs (multiple)", command=self.run_music_cutter).pack(side="right", padx=3)
        ttk.Button(music, text="Open music clips", command=self.open_music_folder).pack(side="right", padx=3)

        stockos = ttk.LabelFrame(publish_tab, text="StockOS Video Queue", padding=6)
        stockos.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Checkbutton(
            stockos,
            text="Automatically send new Ready clips",
            variable=self.stockos_auto,
            command=self.toggle_stockos_auto,
        ).pack(side="left", padx=4)
        ttk.Label(stockos, textvariable=self.stockos_status).pack(side="left", padx=12)
        ttk.Button(stockos, text="REVIEW READY & SEND", command=self.sync_ready_to_stockos).pack(side="right", padx=3)
        ttk.Button(stockos, text="Open StockOS / Schedule", command=self.open_stockos).pack(side="right", padx=3)
        ttk.Label(
            stockos,
            text="Publish pace: 3 clips/week · extra Ready clips wait in queue",
        ).pack(side="right", padx=12)

        ttk.Label(find_tab, text="Paste one or more video URLs (one per line):").pack(anchor="w", padx=10)
        self.urls = tk.Text(find_tab, height=4)
        self.urls.pack(fill="x", padx=10, pady=(3, 8))

        buttons = ttk.Frame(self.root, padding=(10, 0))
        buttons.pack(fill="x")
        primary_actions = ttk.Frame(buttons)
        primary_actions.pack(fill="x", pady=(2, 3))
        secondary_actions = ttk.Frame(buttons)
        secondary_actions.pack(fill="x", pady=(0, 3))
        ttk.Button(primary_actions, text="Add to queue", command=self.add_urls).pack(side="left", padx=3)
        ttk.Button(primary_actions, text="Download selected", command=self.download_selected).pack(side="left", padx=3)
        ttk.Button(primary_actions, text="Inspect URL", command=self.inspect_selected_url).pack(side="left", padx=3)
        ttk.Button(primary_actions, text="Open selected in browser", command=self.open_selected).pack(side="left", padx=3)
        ttk.Button(primary_actions, text="Remove selected", command=self.remove_selected).pack(side="left", padx=3)
        ttk.Button(primary_actions, text="FULL QUEUE", command=self.show_full_queue).pack(side="right", padx=3)
        ttk.Button(secondary_actions, text="Clear completed", command=self.clear_completed).pack(side="left", padx=3)
        ttk.Button(secondary_actions, text="Clear all", command=self.clear_all).pack(side="left", padx=3)
        ttk.Button(secondary_actions, text="Clear log", command=self.clear_log).pack(side="left", padx=3)
        ttk.Button(secondary_actions, text="Pause / Resume", command=self.toggle_pause).pack(side="right", padx=3)
        ttk.Button(secondary_actions, text="Stop after current", command=self.request_stop).pack(side="right", padx=3)
        ttk.Button(secondary_actions, text="Retry failed", command=self.retry_failed).pack(side="right", padx=3)
        ttk.Button(secondary_actions, text="Watch & sort browser downloads", command=self.start_watcher).pack(side="right", padx=3)

        cols = ("platform", "category", "url", "status", "reason")
        queue_table = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        queue_table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(queue_table, columns=cols, show="headings", height=14)
        self.tree.heading("platform", text="Platform")
        self.tree.heading("category", text="Category")
        self.tree.heading("url", text="URL")
        self.tree.heading("status", text="Status")
        self.tree.heading("reason", text="Reason / next step")
        self.tree.column("platform", width=100, minwidth=85, stretch=False)
        self.tree.column("category", width=155, minwidth=120, stretch=False)
        self.tree.column("url", width=500, minwidth=300)
        self.tree.column("status", width=125, minwidth=110, stretch=False)
        self.tree.column("reason", width=350, minwidth=220)
        queue_y = ttk.Scrollbar(queue_table, orient="vertical", command=self.tree.yview)
        queue_x = ttk.Scrollbar(queue_table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=queue_y.set, xscrollcommand=queue_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        queue_y.grid(row=0, column=1, sticky="ns")
        queue_x.grid(row=1, column=0, sticky="ew")
        queue_table.rowconfigure(0, weight=1)
        queue_table.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda _event: self.open_selected())

        ttk.Label(self.root, text="Activity log:").pack(anchor="w", padx=10)
        self.logbox = tk.Text(self.root, height=5, state="disabled")
        self.logbox.pack(fill="both", padx=10, pady=(3, 5))
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x")
        ttk.Label(bottom, textvariable=self.progress_text, width=24, anchor="w").pack(side="left")
        self.progressbar = ttk.Progressbar(bottom, mode="determinate", maximum=100, length=220)
        self.progressbar.pack(side="left", padx=5)
        ttk.Label(bottom, textvariable=self.status, relief="sunken", anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Label(bottom, textvariable=self.summary, relief="sunken", anchor="e").pack(side="right")

    def emit(self, text):
        try:
            with LOG_FILE.open("a", encoding="utf-8") as log:
                log.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
        except Exception:
            pass
        self.events.put(text)

    def flush_events(self):
        while True:
            try:
                text = self.events.get_nowait()
            except queue.Empty:
                break
            self.logbox.configure(state="normal")
            self.logbox.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
            self.status.set(text)
        self.update_summary()
        self.root.after(200, self.flush_events)

    def update_summary(self):
        counts = {}
        for item in self.tree.get_children():
            state = self.tree.set(item, "status") or "queued"
            counts[state] = counts.get(state, 0) + 1
        total = sum(counts.values())
        details = " | ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        self.summary.set(f"Total: {total}" + (f" | {details}" if details else ""))

    def set_progress(self, completed, total, label=None):
        def update():
            percent = 0 if total <= 0 else min(100, completed * 100 / total)
            self.progressbar["value"] = percent
            self.progress_text.set(label or f"Completed {completed}/{total}")
        self.root.after(0, update)

    def infer_product_category(self, text=""):
        requested = self.product_category.get().strip()
        if requested in PRODUCT_CATEGORIES:
            return requested
        searchable = (text or self.keyword.get()).casefold()
        for label, config in PRODUCT_CATEGORIES.items():
            if label == "อื่นๆ (Other)":
                continue
            if any(term.casefold() in searchable for term in config["keywords"]):
                return label
        return "อื่นๆ (Other)"

    def category_download_dir(self, platform, category=None):
        label = category if category in PRODUCT_CATEGORIES else self.infer_product_category()
        folder = PLATFORM_DIRS[platform] / PRODUCT_CATEGORIES[label]["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def queue_values(self, platform, url, status="queued", category=None, reason=""):
        label = category if category in PRODUCT_CATEGORIES else self.infer_product_category()
        return platform, label, url, status, reason

    def previous_download_issue(self, platform):
        return "needs attention", "Old attempt did not save the cause; use Retry failed for an exact reason"

    def classify_download_issue(self, platform, detail, browser_reason=""):
        message = (detail or "").casefold()
        if "bytes read" in message or "more expected" in message or "incomplete read" in message:
            return "retry needed", "Video transfer stopped early; resume retry did not finish"
        if "timed out" in message or "timeout" in message:
            return "retry needed", "Connection timed out; try this URL again"
        if "fresh cookies" in message:
            return "site restricted", browser_reason or "Site requested fresh cookies; open the post to check access"
        if "no video formats" in message:
            return "no video stream", browser_reason or "The page did not expose a downloadable video"
        if "404" in message or "not available right now" in message:
            return "unavailable", "Post page is unavailable or the URL has expired"
        if "captcha" in message or "login" in message or "sign in" in message:
            return "login required", "Site requires interaction in the browser"
        if "403" in message or "forbidden" in message:
            return "site restricted", "Site denied access to the video"
        if browser_reason:
            return "needs attention", browser_reason[:120]
        return "needs attention", (detail or f"{platform} download failed; see Activity log")[:120]

    def show_full_queue(self):
        if self.full_queue_window and self.full_queue_window.winfo_exists():
            self.full_queue_window.deiconify()
            self.full_queue_window.lift()
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Hair Tutorial Collector — Full Download Queue")
        dialog.geometry("1450x760")
        dialog.minsize(950, 500)
        self.full_queue_window = dialog

        filters = ttk.Frame(dialog, padding=10)
        filters.pack(fill="x")
        search_var = tk.StringVar()
        platform_var = tk.StringVar(value="All platforms")
        status_var = tk.StringVar(value="All statuses")
        category_var = tk.StringVar(value="All categories")
        count_var = tk.StringVar(value="0 rows")
        ttk.Label(filters, text="Filter:").pack(side="left")
        search_entry = ttk.Entry(filters, textvariable=search_var, width=34)
        search_entry.pack(side="left", padx=5)
        ttk.Combobox(filters, textvariable=platform_var, state="readonly", width=16,
                     values=("All platforms", *PLATFORM_DIRS.keys())).pack(side="left", padx=5)
        ttk.Combobox(filters, textvariable=category_var, state="readonly", width=24,
                     values=("All categories", *PRODUCT_CATEGORIES.keys())).pack(side="left", padx=5)
        ttk.Combobox(filters, textvariable=status_var, state="readonly", width=18,
                     values=("All statuses", "queued", "downloading", "ready", "needs-review",
                             "needs-trim", "retry needed", "site restricted", "no video stream",
                             "login required", "unavailable", "needs attention", "error",
                             "already downloaded")).pack(side="left", padx=5)
        ttk.Label(filters, textvariable=count_var).pack(side="right")

        table_frame = ttk.Frame(dialog, padding=(10, 0, 10, 8))
        table_frame.pack(fill="both", expand=True)
        columns = ("number", "platform", "category", "url", "status", "reason")
        table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.full_queue_tree = table
        for column, title in zip(columns, ("#", "Platform", "Category", "URL", "Status", "Reason / next step")):
            table.heading(column, text=title)
        table.column("number", width=55, minwidth=45, stretch=False, anchor="center")
        table.column("platform", width=120, minwidth=90, stretch=False)
        table.column("category", width=190, minwidth=140, stretch=False)
        table.column("url", width=610, minwidth=350)
        table.column("status", width=150, minwidth=120, stretch=False)
        table.column("reason", width=350, minwidth=240)
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        table.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        def matching_rows():
            needle = search_var.get().strip().casefold()
            rows = []
            for number, item in enumerate(self.tree.get_children(), 1):
                platform = self.tree.set(item, "platform")
                category = self.tree.set(item, "category")
                url = self.tree.set(item, "url")
                status = self.tree.set(item, "status")
                reason = self.tree.set(item, "reason")
                if platform_var.get() != "All platforms" and platform != platform_var.get():
                    continue
                if category_var.get() != "All categories" and category != category_var.get():
                    continue
                if status_var.get() != "All statuses" and status != status_var.get():
                    continue
                if needle and needle not in f"{platform} {category} {url} {status} {reason}".casefold():
                    continue
                rows.append((item, (number, platform, category, url, status, reason)))
            return rows

        def refresh():
            if not dialog.winfo_exists():
                return
            selected = set(table.selection())
            for existing_item in table.get_children():
                table.delete(existing_item)
            rows = matching_rows()
            for item, values in rows:
                table.insert("", "end", iid=item, values=values)
            for item in selected:
                if table.exists(item):
                    table.selection_add(item)
            count_var.set(f"{len(rows)} row(s)")

        def sync_main_selection():
            chosen = [item for item in table.selection() if self.tree.exists(item)]
            self.tree.selection_set(chosen)
            if chosen:
                self.tree.see(chosen[0])
            return chosen

        def open_from_full():
            if sync_main_selection():
                self.open_selected()

        def download_from_full():
            if sync_main_selection():
                self.download_selected()

        def remove_from_full():
            chosen = sync_main_selection()
            if chosen and messagebox.askyesno("Remove rows", f"Remove {len(chosen)} selected row(s) from the queue?", parent=dialog):
                self.remove_selected()
                refresh()

        actions = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="Download selected", command=download_from_full).pack(side="left", padx=3)
        ttk.Button(actions, text="Open selected", command=open_from_full).pack(side="left", padx=3)
        ttk.Button(actions, text="Remove selected", command=remove_from_full).pack(side="left", padx=3)
        ttk.Button(actions, text="Refresh", command=refresh).pack(side="left", padx=3)
        ttk.Button(actions, text="Close", command=dialog.destroy).pack(side="right", padx=3)
        table.bind("<Double-1>", lambda _event: open_from_full())
        for variable in (search_var, platform_var, category_var, status_var):
            variable.trace_add("write", lambda *_args: refresh())

        def periodic_refresh():
            if dialog.winfo_exists():
                refresh()
                dialog.after(1200, periodic_refresh)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        refresh()
        periodic_refresh()
        search_entry.focus_set()

    def add_urls(self):
        selected = self.selected_platforms()
        if not selected:
            messagebox.showinfo("Select a platform", "Select at least one platform.")
            return
        raw = self.urls.get("1.0", "end").strip().splitlines()
        added = 0
        existing = {self.normalize_url(self.tree.set(i, "url")) for i in self.tree.get_children()}
        downloaded = self.downloaded_urls()
        for url in (x.strip() for x in raw):
            normalized = self.normalize_url(url)
            if not url.startswith(("http://", "https://")) or normalized in existing:
                continue
            if normalized in downloaded or self.video_already_on_disk(url):
                self.emit(f"Skipped previously downloaded URL: {url}")
                continue
            platform = self.detect_platform(url) or selected[0]
            self.tree.insert("", "end", values=self.queue_values(platform, normalized))
            existing.add(normalized)
            added += 1
        self.urls.delete("1.0", "end")
        self.save_queue()
        self.emit(f"Added {added} URL(s)")

    def load_queue(self):
        if not QUEUE_FILE.exists():
            return
        migrated = False
        with QUEUE_FILE.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                category = row.get("category") or self.infer_product_category()
                status = row.get("status", "queued")
                reason = row.get("reason") or ""
                if status == "browser needed":
                    status, reason = self.previous_download_issue(row["platform"])
                    migrated = True
                self.tree.insert("", "end", values=self.queue_values(
                    row["platform"], row["url"], status, category, reason,
                ))
        if migrated:
            self.save_queue()

    def save_queue(self):
        with self.queue_file_lock:
            with QUEUE_FILE.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(["platform", "category", "url", "status", "reason"])
                for item in self.tree.get_children():
                    writer.writerow(self.tree.item(item, "values"))

    def remove_selected(self):
        for item in self.tree.selection():
            self.tree.delete(item)
        self.save_queue()

    def clear_completed(self):
        count = 0
        for item in list(self.tree.get_children()):
            if self.tree.set(item, "status") in (
                "done", "ready", "needs-review", "needs-trim", "too-short",
                "low resolution", "already downloaded",
            ):
                self.tree.delete(item)
                count += 1
        self.save_queue()
        self.emit(f"Cleared {count} completed row(s); download history was kept")

    def clear_all(self):
        if not messagebox.askyesno("Clear queue", "Clear every row from the queue?\nDownloaded files and history will be kept."):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.save_queue()
        self.emit("Queue cleared; downloaded files and history were kept")

    def clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        try:
            LOG_FILE.write_text("", encoding="utf-8")
        except Exception:
            pass
        self.status.set("Activity log cleared")

    def normalize_url(self, url):
        parsed = urllib.parse.urlsplit(url.strip())
        host = parsed.netloc.lower()
        query = parsed.query if ("rednote.com" in host or "xiaohongshu.com" in host) else ""
        return urllib.parse.urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/"), query, ""))

    def downloaded_urls(self):
        urls = set()
        if not HISTORY_FILE.exists():
            return urls
        try:
            with HISTORY_FILE.open("r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    if row.get("url"):
                        urls.add(self.normalize_url(row["url"]))
        except Exception:
            pass
        return urls

    def video_key(self, url):
        patterns = (r"/video/(BV[0-9A-Za-z]+)", r"/video/(\d+)",
                    r"/(?:explore|discovery/item)/(\w+)", r"/search_result/([0-9a-f]{20,})")
        for pattern in patterns:
            match = re.search(pattern, url, re.I)
            if match:
                return match.group(1)
        return ""

    def video_already_on_disk(self, url):
        key = self.video_key(url)
        if not key:
            return False
        folders = list(PLATFORM_DIRS.values()) + [EDITED_DIR, REJECTED_DIR, REJECTED_SHORT_DIR]
        return any(key.lower() in path.name.lower() for folder in folders
                   if folder.exists() for path in folder.rglob("*")
                   if path.is_file() and path.suffix.lower() in VIDEO_EXTS)

    def candidate_is_known(self, url, seen_urls, seen_keys):
        normalized = self.normalize_url(url)
        key = self.video_key(normalized)
        return normalized in seen_urls or (key and key in seen_keys)

    def disk_video_keys(self):
        keys = set()
        folders = list(PLATFORM_DIRS.values()) + [EDITED_DIR, REJECTED_DIR, REJECTED_SHORT_DIR]
        pattern = re.compile(r"(BV[0-9A-Za-z]+|\d{16,}|[0-9a-f]{20,})", re.I)
        for folder in folders:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
                    continue
                keys.update(match.group(1) for match in pattern.finditer(path.name))
        return keys

    def remember_candidate(self, url, seen_urls, seen_keys):
        normalized = self.normalize_url(url)
        seen_urls.add(normalized)
        key = self.video_key(normalized)
        if key:
            seen_keys.add(key)
        return normalized

    def selected_item(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select a URL", "Select one queued URL first.")
            return None
        return selected[0]

    def open_selected(self):
        item = self.selected_item()
        if item:
            self.last_opened_url = self.tree.set(item, "url")
            webbrowser.open(self.last_opened_url)
            self.emit("Opened selected URL in the default browser")

    def inspect_selected_url(self):
        item = self.selected_item()
        if not item:
            return
        platform = self.tree.set(item, "platform")
        url = self.tree.set(item, "url")
        threading.Thread(target=self.inspect_url_worker, args=(platform, url), daemon=True).start()

    def inspect_url_worker(self, platform, url):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(VENDOR_DIR)
        command = [sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download",
                   "--no-playlist"]
        xhs_profile = APP_DIR / "xhs_browser_profile"
        if platform == "Xiaohongshu" and xhs_profile.exists():
            command += ["--cookies-from-browser", f"chrome:{xhs_profile}"]
        elif self.use_cookies.get():
            command += ["--cookies-from-browser", "chrome:Default"]
        command.append(url)
        self.emit(f"Inspecting {platform} URL without downloading...")
        try:
            result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=120,
                                    creationflags=NO_WINDOW)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
                raise RuntimeError(detail[0] if detail else "No public metadata available")
            data = json.loads(result.stdout)
            duration = data.get("duration")
            width = data.get("width")
            height = data.get("height")
            lines = [
                f"Title: {data.get('title') or '-'}",
                f"Creator: {data.get('uploader') or data.get('channel') or '-'}",
                f"Duration: {duration:.1f} seconds" if isinstance(duration, (int, float)) else "Duration: -",
                f"Resolution: {width}x{height}" if width and height else "Resolution: determined during download",
                f"Platform: {platform}",
                "",
                "This preview does not download the video.",
            ]
            self.root.after(0, lambda: messagebox.showinfo("URL preview", "\n".join(lines)))
            self.emit("URL inspection finished")
        except Exception as exc:
            detail = str(exc)
            self.emit(f"URL inspection unavailable: {detail}")
            self.root.after(0, lambda detail=detail: messagebox.showwarning(
                "Preview unavailable", f"The website did not provide public metadata.\n\n{detail}"))

    def open_keyword_list(self):
        if KEYWORDS_FILE.exists():
            os.startfile(str(KEYWORDS_FILE))
            self.emit("Opened the beauty keyword list")
        else:
            messagebox.showerror("File not found", str(KEYWORDS_FILE))

    def toggle_pause(self):
        if self.download_gate.is_set():
            self.download_gate.clear()
            self.emit("Queue paused; the current download may finish")
        else:
            self.download_gate.set()
            self.stop_after_current.clear()
            self.emit("Queue resumed")

    def request_stop(self):
        self.stop_after_current.set()
        self.download_gate.set()
        self.emit("The queue will stop after the current item")

    def retry_failed(self):
        items = [item for item in self.tree.get_children()
                 if self.tree.set(item, "status") in (
                     "error", "browser needed", "retry needed", "site restricted",
                     "no video stream", "login required", "unavailable", "needs attention")]
        if not items:
            self.emit("No failed items to retry")
            return
        self.stop_after_current.clear()
        self.download_gate.set()
        for item in items:
            self.tree.set(item, "status", "queued")
            self.tree.set(item, "reason", "")
        self.emit(f"Retrying {len(items)} failed item(s)")
        threading.Thread(target=self.batch_download_worker, args=(items,), daemon=True).start()

    def image_search_helper(self):
        path = filedialog.askopenfilename(
            title="Choose a product image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.bmp"), ("All files", "*.*")],
        )
        if not path:
            return
        if Image is None or ImageTk is None:
            self.root.clipboard_clear()
            self.root.clipboard_append(path)
            webbrowser.open("https://lens.google.com/?hl=zh-CN")
            self.emit("Image crop component is unavailable. Opened Google Lens and copied the image path.")
            return
        try:
            original = Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror("Cannot open image", str(exc))
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Search videos from a product image")
        dialog.geometry("1120x720")
        dialog.minsize(900, 620)
        left = ttk.Frame(dialog, padding=10)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(dialog, padding=12)
        right.pack(side="right", fill="y")

        display = original.copy()
        display.thumbnail((760, 610))
        image_tk = ImageTk.PhotoImage(display)
        canvas = tk.Canvas(left, width=display.width, height=display.height,
                           highlightthickness=1, highlightbackground="#888")
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=image_tk, anchor="nw")
        canvas.image = image_tk
        crop_state = {"start": None, "rect": None, "box": None, "saved": None}

        def clamp_point(event):
            return max(0, min(display.width, event.x)), max(0, min(display.height, event.y))

        def crop_start(event):
            crop_state["start"] = clamp_point(event)
            if crop_state["rect"]:
                canvas.delete(crop_state["rect"])
            x, y = crop_state["start"]
            crop_state["rect"] = canvas.create_rectangle(x, y, x, y, outline="#ff3b70", width=3)

        def crop_drag(event):
            if not crop_state["start"]:
                return
            x1, y1 = crop_state["start"]
            x2, y2 = clamp_point(event)
            canvas.coords(crop_state["rect"], x1, y1, x2, y2)

        def crop_end(event):
            if not crop_state["start"]:
                return
            x1, y1 = crop_state["start"]
            x2, y2 = clamp_point(event)
            if abs(x2 - x1) >= 12 and abs(y2 - y1) >= 12:
                crop_state["box"] = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
                crop_note.set("Crop selected — use Lens search or search all platforms.")
            else:
                crop_state["box"] = None
                crop_note.set("Selection was too small; the full image will be used.")

        canvas.bind("<ButtonPress-1>", crop_start)
        canvas.bind("<B1-Motion>", crop_drag)
        canvas.bind("<ButtonRelease-1>", crop_end)

        category_var = tk.StringVar(value=self.infer_product_category(Path(path).stem))
        suggested_keyword = PRODUCT_CATEGORIES[category_var.get()]["search"]
        keyword_var = tk.StringVar(value=suggested_keyword)
        crop_note = tk.StringVar(value="Drag a box around only the product. No selection = use the full image.")
        lens_status = tk.StringVar(value="Lens has not been started.")

        ttk.Label(right, text="1. Crop the product", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=crop_note, wraplength=300).pack(anchor="w", pady=(3, 12))
        ttk.Label(right, text="2. Product category").pack(anchor="w")
        category_box = ttk.Combobox(right, textvariable=category_var, state="readonly", width=34,
                                    values=tuple(PRODUCT_CATEGORIES.keys()))
        category_box.pack(fill="x", pady=(3, 10))
        ttk.Label(right, text="3. Chinese search words").pack(anchor="w")
        keyword_entry = ttk.Entry(right, textvariable=keyword_var, width=42)
        keyword_entry.pack(fill="x", pady=(3, 5))
        ttk.Label(right, text="The program will use these words on Douyin, Xiaohongshu and Bilibili.",
                  wraplength=300).pack(anchor="w", pady=(0, 10))

        def category_changed(_event=None):
            keyword_var.set(PRODUCT_CATEGORIES[category_var.get()]["search"])

        category_box.bind("<<ComboboxSelected>>", category_changed)

        def save_crop():
            if crop_state["saved"] and Path(crop_state["saved"]).exists():
                return Path(crop_state["saved"])
            box = crop_state["box"]
            if box:
                scale_x = original.width / max(1, display.width)
                scale_y = original.height / max(1, display.height)
                source_box = tuple(int(value * (scale_x if index % 2 == 0 else scale_y))
                                   for index, value in enumerate(box))
                result = original.crop(source_box)
            else:
                result = original.copy()
            IMAGE_SEARCH_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destination = IMAGE_SEARCH_DIR / f"{stamp}_{safe_name(Path(path).stem)}_crop.png"
            result.save(destination, "PNG")
            crop_state["saved"] = str(destination)
            self.last_image_search_path = destination
            self.root.clipboard_clear()
            self.root.clipboard_append(str(destination))
            self.emit(f"Saved product crop: {destination}")
            return destination

        def paste_and_extract():
            try:
                clipboard = self.root.clipboard_get()
            except Exception:
                clipboard = ""
            terms = self.extract_chinese_terms(clipboard)
            if terms:
                keyword_var.set(self.build_image_search_query(terms, category_var.get()))
                lens_status.set(f"Extracted Chinese words: {', '.join(terms[:5])}")
            elif clipboard.strip():
                keyword_var.set(clipboard.strip().replace("\n", " ")[:160])
                lens_status.set("Pasted text. No clear Chinese product phrase was detected.")
            else:
                messagebox.showinfo("Clipboard is empty", "Copy a product name or Lens result first.", parent=dialog)

        def lens_finished(terms, detail):
            if not dialog.winfo_exists():
                return
            if terms:
                keyword_var.set(self.build_image_search_query(terms, category_var.get()))
                lens_status.set(f"Found Chinese words: {', '.join(terms[:6])}")
                keyword_entry.focus_set()
            else:
                lens_status.set(detail or "No Chinese product words were found. Copy a Lens result and use Paste / extract.")

        def search_lens():
            destination = save_crop()
            if not messagebox.askyesno(
                "Send cropped image to Google Lens",
                "Google Lens needs a copy of the cropped product image. Continue?\n\n"
                "If Google shows CAPTCHA or login, complete it yourself; the program will not bypass it.",
                parent=dialog,
            ):
                return
            lens_status.set("Opening Google Lens and looking for Chinese product words...")
            threading.Thread(
                target=self.lens_keyword_worker,
                args=(destination, lambda terms, detail: self.root.after(0, lens_finished, terms, detail)),
                daemon=True,
            ).start()

        def search_platforms():
            query = keyword_var.get().strip()
            if not query:
                messagebox.showinfo("Chinese words required", "Enter or extract Chinese product words first.", parent=dialog)
                return
            save_crop()
            self.product_category.set(category_var.get())
            self.keyword.set(query)
            dialog.destroy()
            self.emit(f"Image-assisted search started: {query} [{category_var.get()}]")
            self.auto_find()

        ttk.Button(right, text="SEARCH LENS + EXTRACT CHINESE", command=search_lens).pack(fill="x", pady=(8, 4))
        ttk.Button(right, text="PASTE / EXTRACT FROM CLIPBOARD", command=paste_and_extract).pack(fill="x", pady=4)
        ttk.Label(right, textvariable=lens_status, wraplength=300).pack(anchor="w", pady=8)
        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="SEARCH ALL 3 PLATFORMS", command=search_platforms).pack(fill="x", pady=4)
        ttk.Button(right, text="Save crop only", command=save_crop).pack(fill="x", pady=4)
        ttk.Button(right, text="Cancel", command=dialog.destroy).pack(fill="x", pady=4)

    def extract_chinese_terms(self, text):
        ignored = {
            "搜索", "图片", "相关", "结果", "视觉匹配", "网页", "商品", "查看", "登录",
            "更多", "全部", "相似图片", "添加到", "分享", "翻译", "购物", "价格",
        }
        terms = []
        for line in (text or "").splitlines():
            for match in re.findall(r"[\u3400-\u9fff]{2,18}", line):
                term = match.strip()
                if term in ignored or any(term.startswith(prefix) for prefix in ("搜索", "查看", "登录")):
                    continue
                if term not in terms:
                    terms.append(term)
        product_markers = tuple(
            marker for config in PRODUCT_CATEGORIES.values() for marker in config["keywords"]
            if re.search(r"[\u3400-\u9fff]", marker)
        )
        return sorted(terms, key=lambda term: (not any(marker in term for marker in product_markers), len(term)))[:15]

    def build_image_search_query(self, terms, category):
        fallback = PRODUCT_CATEGORIES.get(category, PRODUCT_CATEGORIES["อื่นๆ (Other)"])["search"]
        useful = [term for term in terms if 2 <= len(term) <= 14]
        if not useful:
            return fallback
        primary = useful[0]
        category_words = fallback.split()[:2]
        combined = []
        for word in (primary, *category_words, "教程"):
            if word and word not in combined:
                combined.append(word)
        return " ".join(combined)

    def lens_keyword_worker(self, image_path, callback):
        if sync_playwright is None:
            webbrowser.open("https://lens.google.com/?hl=zh-CN")
            callback([], "Google Lens opened. Upload the copied crop, then use Paste / extract.")
            return
        chrome_candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((candidate for candidate in chrome_candidates if candidate.exists()), None)
        if not chrome:
            callback([], "Google Chrome was not found.")
            return
        profile = APP_DIR / "lens_browser_profile"
        context = None
        try:
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(profile), executable_path=str(chrome), headless=False,
                    locale="zh-CN", viewport={"width": 1280, "height": 850},
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://lens.google.com/?hl=zh-CN", wait_until="domcontentloaded", timeout=60000)
                file_input = page.locator("input[type='file']")
                if file_input.count() < 1:
                    for selector in ("button[aria-label*='图片']", "button[aria-label*='image']", "[data-action='upload']"):
                        try:
                            page.locator(selector).first.click(timeout=2000)
                            if page.locator("input[type='file']").count():
                                break
                        except Exception:
                            pass
                file_input = page.locator("input[type='file']")
                if file_input.count() < 1:
                    callback([], "Lens upload control was not available. Use Paste / extract after searching manually.")
                    return
                file_input.first.set_input_files(str(image_path))
                terms = []
                for _attempt in range(30):
                    page.wait_for_timeout(2000)
                    try:
                        body = page.locator("body").inner_text(timeout=5000)
                    except Exception:
                        body = ""
                    terms = self.extract_chinese_terms(body)
                    if terms and ("/search" in page.url or "/upload" in page.url):
                        break
                if terms:
                    callback(terms, "")
                    self.emit(f"Google Lens extracted Chinese candidates: {', '.join(terms[:8])}")
                else:
                    callback([], "Lens returned no clear Chinese words. Copy a useful result and click Paste / extract.")
                    self.emit("Google Lens returned no clear Chinese product words")
        except Exception as exc:
            callback([], f"Lens search needs manual help: {exc}")
            self.emit(f"Google Lens image search did not finish automatically: {exc}")
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass

    def choose_videos_for_editing(self):
        return filedialog.askopenfilenames(
            title="Choose videos",
            initialdir=str(BASE),
            filetypes=[("Video files", "*.mp4 *.webm *.mkv *.mov *.m4v"), ("All files", "*.*")],
        )

    def open_ready_folder(self):
        READY_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(READY_DIR))

    def open_needs_review_folder(self):
        NEEDS_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(NEEDS_REVIEW_DIR))

    def open_needs_trim_folder(self):
        NEEDS_TRIM_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(NEEDS_TRIM_DIR))

    def choose_fixed_review_files(self, title):
        files = filedialog.askopenfilenames(
            title=title,
            initialdir=str(EDITED_DIR),
            filetypes=[("Video files", "*.mp4 *.webm *.mkv *.mov *.m4v"), ("All files", "*.*")],
        )
        allowed = {NEEDS_REVIEW_DIR.resolve(), NEEDS_TRIM_DIR.resolve()}
        accepted, rejected = [], []
        for filename in files:
            path = Path(filename)
            if path.parent.resolve() in allowed:
                accepted.append(path)
            else:
                rejected.append(path.name)
        if rejected:
            messagebox.showwarning(
                "Choose Needs Review / Needs Trim files",
                "These files were skipped because they are outside Needs_Review and Needs_Trim:\n"
                + "\n".join(rejected[:8]),
            )
        return accepted

    def process_fixed_dialog(self):
        files = self.choose_fixed_review_files(
            "Choose fixed files — apply Automatic text mode and send to Ready"
        )
        if files:
            threading.Thread(target=self.process_fixed_files, args=(files,), daemon=True).start()

    def approve_fixed_dialog(self):
        files = self.choose_fixed_review_files(
            "Choose already-finished files — approve and move directly to Ready"
        )
        if files:
            threading.Thread(target=self.approve_fixed_files, args=(files,), daemon=True).start()

    def process_fixed_files(self, files):
        """Re-run the selected text mode, then archive the reviewed source automatically."""
        if self.cleaning_active.is_set():
            self.emit("A video editing job is already running")
            return
        self.cleaning_active.set()
        completed, failures = 0, []
        try:
            from media_pipeline import inspect_video, move_with_sidecar, write_metadata

            total = len(files)
            self.set_progress(0, total, f"Review processing 0/{total}")
            for index, source in enumerate(files, start=1):
                try:
                    info = inspect_video(source)
                    duration = float(info.get("duration_seconds") or 0)
                    if duration < max(1, int(self.min_duration.get())):
                        raise RuntimeError(
                            f"clip is {duration:.1f}s; minimum is {self.min_duration.get()}s"
                        )
                    if duration > max(2, int(self.max_duration.get())):
                        raise RuntimeError(
                            f"clip is still {duration:.1f}s; trim to {self.max_duration.get()}s or less first"
                        )
                    metadata = self.stockos_connector._read_sidecar(source)
                    metadata.update(info)
                    metadata.update({
                        "manual_review_completed_at": datetime.now().isoformat(timespec="seconds"),
                        "review_source_folder": str(source.parent),
                    })
                    state, final_path = self.prepare_downloaded_copy(
                        source, "ready", metadata
                    )
                    if state != "ready":
                        raise RuntimeError("text check still found items; the new copy remains in Needs_Review")
                    archived = move_with_sidecar(source, REVIEWED_SOURCE_DIR)
                    final_metadata = self.stockos_connector._read_sidecar(final_path)
                    final_metadata.update({
                        "source_file": str(archived),
                        "review_source_archived": True,
                    })
                    write_metadata(final_path, final_metadata)
                    completed += 1
                    self.emit(f"Reviewed source archived: {archived.name}")
                    self.emit(f"Review workflow completed -> Ready: {final_path.name}")
                except Exception as exc:
                    failures.append(f"{source.name}: {exc}")
                    self.emit(f"Review workflow stopped for {source.name}: {exc}")
                self.set_progress(index, total, f"Review processing {index}/{total}")
            summary = (
                f"Ready: {completed}\nNeeds attention: {len(failures)}\n"
                f"Ready folder: {READY_DIR}"
            )
            if failures:
                summary += "\n\n" + "\n".join(failures[:8])
            self.root.after(0, lambda text=summary: messagebox.showinfo("Review workflow finished", text))
        finally:
            self.cleaning_active.clear()

    def approve_fixed_files(self, files):
        """Trust a human-reviewed edit, create its cover, and move it to Ready."""
        if self.cleaning_active.is_set():
            self.emit("A video editing job is already running")
            return
        self.cleaning_active.set()
        completed, failures = 0, []
        try:
            from cover_generator import generate_cover
            from media_pipeline import inspect_video, unique_path, with_duration_in_name, write_metadata

            total = len(files)
            self.set_progress(0, total, f"Approving 0/{total}")
            for index, source in enumerate(files, start=1):
                temp_cover = None
                try:
                    info = inspect_video(source)
                    duration = float(info.get("duration_seconds") or 0)
                    if duration < max(1, int(self.min_duration.get())):
                        raise RuntimeError(
                            f"clip is {duration:.1f}s; minimum is {self.min_duration.get()}s"
                        )
                    if duration > max(2, int(self.max_duration.get())):
                        raise RuntimeError(
                            f"clip is still {duration:.1f}s; trim to {self.max_duration.get()}s or less first"
                        )
                    output_name = source.name.replace("_SRC", "_BUUBLE")
                    if output_name == source.name and "_BUUBLE" not in source.stem.upper():
                        output_name = f"{source.stem}_BUUBLE{source.suffix.lower()}"
                    output_name = with_duration_in_name(Path(output_name), duration).name
                    final_path = unique_path(READY_DIR / output_name)
                    final_cover = final_path.with_name(f"{final_path.stem}_COVER.jpg")
                    temp_cover = unique_path(PROCESSING_DIR / f".{final_path.stem}_COVER.jpg")
                    metadata = self.stockos_connector._read_sidecar(source)
                    metadata.update(info)
                    cover_info = generate_cover(
                        source,
                        temp_cover,
                        metadata=metadata,
                        history_path=BASE / "cover_title_history.json",
                    )
                    old_sidecar = source.with_suffix(source.suffix + ".json")
                    shutil.move(str(source), str(final_path))
                    if old_sidecar.exists():
                        old_sidecar.unlink(missing_ok=True)
                    shutil.move(str(temp_cover), str(final_cover))
                    metadata.update({
                        "file": str(final_path),
                        "pipeline_status": "ready",
                        "manual_review_completed_at": datetime.now().isoformat(timespec="seconds"),
                        "approved_without_reprocessing": True,
                        "duration_seconds": info.get("duration_seconds"),
                        "cover_file": str(final_cover),
                        "cover_headline": cover_info["headline"],
                        "cover_generator": cover_info["generator"],
                        "cover_width": cover_info["width"],
                        "cover_height": cover_info["height"],
                    })
                    write_metadata(final_path, metadata)
                    completed += 1
                    self.emit(f"Approved fixed file -> Ready: {final_path.name}")
                except Exception as exc:
                    if temp_cover:
                        Path(temp_cover).unlink(missing_ok=True)
                    failures.append(f"{source.name}: {exc}")
                    self.emit(f"Approval stopped for {source.name}: {exc}")
                self.set_progress(index, total, f"Approving {index}/{total}")
            summary = (
                f"Moved to Ready: {completed}\nNeeds attention: {len(failures)}\n"
                f"Ready folder: {READY_DIR}"
            )
            if failures:
                summary += "\n\n" + "\n".join(failures[:8])
            self.root.after(0, lambda text=summary: messagebox.showinfo("Approval finished", text))
        finally:
            self.cleaning_active.clear()

    def music_files(self):
        found = []
        seen = set()
        for folder in MUSIC_DIRS:
            if not folder.exists():
                continue
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        found.append(resolved)
        return found

    def preferred_music_dir(self):
        populated = next((folder for folder in MUSIC_DIRS if folder.exists() and any(folder.iterdir())), None)
        folder = populated or MUSIC_DIRS[-1]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def refresh_music_status(self):
        files = self.music_files()
        self.music_status.set(f"Music: {len(files)} clip(s) in {self.preferred_music_dir()}")
        return files

    def open_music_folder(self):
        os.startfile(str(self.preferred_music_dir()))

    def run_music_cutter(self):
        if self.music_cutting_active.is_set():
            messagebox.showinfo("Music cutter", "Music cutting is already running")
            return
        sources = filedialog.askopenfilenames(
            title="Choose one or more music files to cut",
            initialdir=str(MUSIC_ROOT),
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")],
        )
        if not sources:
            return
        script = MUSIC_ROOT / "auto_cut_reels.py"
        if not script.exists():
            messagebox.showerror("Music cutter", f"Script was not found:\n{script}")
            return
        self.music_cutting_active.set()

        def worker():
            try:
                from video_cleaner import _ffmpeg_path
                env = os.environ.copy()
                ffmpeg = _ffmpeg_path()
                if ffmpeg:
                    env["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + env.get("PATH", "")
                finished = 0
                failures = []
                for index, source in enumerate(sources, start=1):
                    source_path = Path(source).resolve()
                    safe_stem = re.sub(r'[^\w-]+', '-', source_path.stem, flags=re.UNICODE).strip('-')[:48] or 'song'
                    source_hash = hashlib.sha1(str(source_path).encode('utf-8')).hexdigest()[:8]
                    prefix = f"{safe_stem}-{source_hash}"
                    self.emit(f"Cutting music {index}/{len(sources)}: {source_path.name}")
                    try:
                        completed = subprocess.run(
                            [sys.executable, str(script), str(source_path), "--output", "Reels_Cuts", "--prefix", prefix],
                            cwd=str(MUSIC_ROOT), env=env, capture_output=True, text=True,
                            timeout=7200, creationflags=NO_WINDOW,
                        )
                        if completed.returncode != 0:
                            raise RuntimeError((completed.stderr or completed.stdout or "Music cutter failed")[-500:])
                        finished += 1
                    except Exception as exc:
                        failures.append(f"{source_path.name}: {exc}")
                        self.emit(f"Music cutting failed: {source_path.name}: {exc}")
                self.root.after(0, self.refresh_music_status)
                summary = f"Processed: {finished}/{len(sources)}\nMusic clips: {MUSIC_ROOT / 'Reels_Cuts'}"
                if failures:
                    summary += "\n\nFailed:\n" + "\n".join(failures[:5])
                self.root.after(0, lambda text=summary: messagebox.showinfo("Music cutter", text))
            except Exception as exc:
                self.root.after(0, lambda err=str(exc): messagebox.showerror("Music cutter", err))
            finally:
                self.music_cutting_active.clear()

        self.emit(f"Cutting music from {len(sources)} file(s)")
        threading.Thread(target=worker, daemon=True).start()

    def open_stockos(self):
        webbrowser.open("https://stockos.buublex.com/social-post")

    def toggle_stockos_auto(self):
        if not self.stockos_connector:
            self.stockos_auto.set(False)
            messagebox.showerror("StockOS", "StockOS connector is not available")
            return
        if self.stockos_auto.get() and not self.stockos_connector.configured():
            self.stockos_auto.set(False)
            messagebox.showerror("StockOS", "StockOS connection has not been configured yet")
            return
        self.stockos_connector.set_enabled(self.stockos_auto.get())
        state = "enabled" if self.stockos_auto.get() else "disabled"
        self.stockos_status.set(f"Automatic upload {state}")
        self.emit(f"StockOS automatic upload {state}")

    def enqueue_stockos_upload(self, video_path, *, force=False, source_ready_path=None,
                               planned_publish_at=None):
        if (not force and not self.stockos_auto.get()) or not self.stockos_connector or not self.stockos_connector.configured():
            return False
        path = Path(video_path).resolve()
        if self.stockos_connector.is_uploaded(path):
            return False
        with self.stockos_enqueued_lock:
            if path in self.stockos_enqueued:
                return False
            self.stockos_enqueued.add(path)
        self.stockos_upload_queue.put({
            "path": path,
            "source_ready_path": Path(source_ready_path).resolve() if source_ready_path else None,
            "planned_publish_at": planned_publish_at,
        })
        self.stockos_status.set(f"Queued: {path.name}")
        self.emit(f"Queued for StockOS: {path.name}")
        return True

    def sync_ready_to_stockos(self):
        if not self.stockos_connector or not self.stockos_connector.configured():
            messagebox.showerror("StockOS", "StockOS connection has not been configured yet")
            return
        pending = self.stockos_connector.pending_videos(READY_DIR)
        if not pending:
            self.stockos_status.set("No new Ready clips to upload")
            messagebox.showinfo("StockOS", "No unsent clips are available in Ready.")
            return
        music = self.refresh_music_status()
        if not music:
            messagebox.showerror(
                "Music library is empty",
                "Add music clips to one of these folders before sending:\n\n"
                + "\n".join(str(folder) for folder in MUSIC_DIRS),
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Review Ready clips before StockOS")
        dialog.geometry("1040x620")
        dialog.transient(self.root)
        ttk.Label(
            dialog,
            text="1) Preview  2) Select approved clips  3) Add random music and send  4) StockOS assigns the next free 3-per-week slots",
            padding=10,
        ).pack(anchor="w")
        columns = ("name", "duration", "resolution", "planned")
        ready_tree = ttk.Treeview(dialog, columns=columns, show="headings", selectmode="extended", height=17)
        for key, title, width in (("name", "Ready file", 590), ("duration", "Seconds", 80),
                                  ("resolution", "Resolution", 100), ("planned", "Planned publish", 170)):
            ready_tree.heading(key, text=title)
            ready_tree.column(key, width=width, anchor="w")
        for path in pending:
            data = self.stockos_connector._read_sidecar(path)
            ready_tree.insert("", "end", iid=str(path), values=(
                path.name,
                data.get("duration_seconds", "?"),
                data.get("resolution", "?"),
                "Next free weekly slot",
            ))
        ready_tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        plan = ttk.LabelFrame(dialog, text="Smooth publishing queue", padding=8)
        plan.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Label(
            plan,
            text=(
                "Select 10, 20, 30 or more clips at once. StockOS appends them after the existing queue "
                "at 3 clips/week. Ready means approved, but each clip waits for its scheduled time."
            ),
        ).pack(side="left")

        def selected_paths():
            return [Path(item) for item in ready_tree.selection()]

        def preview():
            chosen = selected_paths()
            if not chosen:
                messagebox.showinfo("Preview", "Select one Ready clip first.", parent=dialog)
                return
            os.startfile(str(chosen[0]))

        def select_all():
            ready_tree.selection_set(ready_tree.get_children())

        def queue_selected():
            chosen = selected_paths()
            if not chosen:
                messagebox.showinfo("StockOS", "Select at least one approved clip.", parent=dialog)
                return
            estimated_weeks = (len(chosen) + 2) // 3
            if not messagebox.askyesno(
                "Send approved clips",
                f"Add a random music clip and send {len(chosen)} approved video(s) to StockOS?\n\n"
                f"This batch will span about {estimated_weeks} week(s) at 3 clips/week. "
                "StockOS will continue after the existing queue.\n\n"
                "The Ready originals will be archived only after a successful upload.",
                parent=dialog,
            ):
                return
            dialog.destroy()
            threading.Thread(
                target=self.prepare_reviewed_for_stockos,
                args=(chosen, None), daemon=True,
            ).start()

        actions = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="Preview selected", command=preview).pack(side="left", padx=3)
        ttk.Button(actions, text="Select all", command=select_all).pack(side="left", padx=3)
        ttk.Button(actions, text="Open Ready folder", command=self.open_ready_folder).pack(side="left", padx=3)
        ttk.Button(actions, text="Open StockOS / Schedule", command=self.open_stockos).pack(side="right", padx=3)
        ttk.Button(actions, text="ADD MUSIC & SEND SELECTED", command=queue_selected).pack(side="right", padx=3)

    def _choose_music(self):
        choices = self.music_files()
        if not choices:
            raise RuntimeError("Music library is empty")
        if len(choices) > 1 and self.last_music_path in choices:
            choices = [path for path in choices if path != self.last_music_path]
        selected = random.choice(choices)
        self.last_music_path = selected
        return selected

    def _write_schedule_plan(self, video_path, planned_at, music_path):
        new_file = not SCHEDULE_PLAN_FILE.exists()
        with self.queue_file_lock, SCHEDULE_PLAN_FILE.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter="\t")
            if new_file:
                writer.writerow(["planned_publish_at", "ready_file", "music_file", "status"])
            writer.writerow([
                planned_at.isoformat(timespec="minutes") if planned_at else "",
                str(video_path), str(music_path), "queued_for_stockos_review",
            ])

    def prepare_reviewed_for_stockos(self, paths, slots=None):
        from media_pipeline import unique_path, write_metadata
        from video_cleaner import add_music_to_video

        slots = list(slots or [None] * len(paths))
        queued = 0
        failures = []
        self.set_progress(0, len(paths), "Preparing music 0/0")
        for index, (source, planned_at) in enumerate(zip(paths, slots), start=1):
            source = Path(source)
            prepared = None
            try:
                music = self._choose_music()
                prepared = unique_path(STOCKOS_PENDING_DIR / f"{source.stem}_MUSIC.mp4")
                self.emit(f"Adding music {music.name} -> {source.name}")
                add_music_to_video(source, prepared, music, volume=0.24)
                metadata = self.stockos_connector._read_sidecar(source)
                metadata.update({
                    "file": str(prepared),
                    "reviewed_source_file": str(source),
                    "pipeline_status": "stockos-pending",
                    "music_added": True,
                    "music_file": str(music),
                    "music_volume": 0.24,
                    "source_audio_replaced": True,
                    "planned_publish_at": planned_at.isoformat(timespec="minutes") if planned_at else None,
                    "planned_timezone": "Asia/Bangkok",
                })
                write_metadata(prepared, metadata)
                self._write_schedule_plan(source, planned_at, music)
                if self.enqueue_stockos_upload(
                    prepared, force=True, source_ready_path=source,
                    planned_publish_at=metadata["planned_publish_at"],
                ):
                    queued += 1
                else:
                    raise RuntimeError("Clip could not be added to the StockOS queue")
            except Exception as exc:
                failures.append(f"{source.name}: {exc}")
                self.emit(f"StockOS preparation failed for {source.name}: {exc}")
                if prepared and prepared.exists():
                    prepared.unlink(missing_ok=True)
                    prepared.with_suffix(prepared.suffix + ".json").unlink(missing_ok=True)
            self.set_progress(index, len(paths), f"Music ready {index}/{len(paths)}")

        summary = (
            f"Queued for StockOS review: {queued}\nFailed: {len(failures)}\n\n"
            "StockOS will append each processed clip to the next free 3-per-week slot. "
            "Ready clips are approved automatically and will publish only at their scheduled times."
        )
        self.root.after(0, lambda text=summary: messagebox.showinfo("StockOS queue", text))
        if queued:
            self.root.after(0, self.open_stockos)

    def stockos_upload_worker(self):
        while True:
            job = self.stockos_upload_queue.get()
            path = Path(job["path"])
            source_ready_path = job.get("source_ready_path")
            try:
                self.root.after(0, lambda p=path: self.stockos_status.set(f"Uploading: {p.name}"))
                def report_progress(percent, stage, status, p=path):
                    label = f"StockOS {percent}% — {stage}: {p.name}"
                    self.root.after(0, lambda text=label: self.stockos_status.set(text))

                schedule_assigned = False
                result = self.stockos_connector.upload_video(
                    path,
                    progress_callback=report_progress,
                )
                if result.get("skipped"):
                    self.emit(f"StockOS skipped existing clip: {path.name}")
                else:
                    self.emit(f"StockOS ready for review: {path.name} ({result.get('id', 'unknown ID')})")
                    if self.stockos_connector.config.get("schedule_after_reviewed_upload", True):
                        try:
                            self.stockos_connector.schedule_recommended([result.get("id")])
                            self.stockos_connector._update_sidecar(path, {
                                "schedule_status": "recommended_weekly_slot_assigned",
                                "schedule_pace": "3_per_week",
                                "scheduled_at": datetime.now().isoformat(timespec="seconds"),
                            })
                            schedule_assigned = True
                            self.emit(f"StockOS weekly slot assigned: {path.name}")
                        except Exception as schedule_exc:
                            # The upload is already safely stored in StockOS. Keep moving the
                            # local files so a retry cannot create a duplicate; the clip remains
                            # visible in StockOS where Recommended schedule can be clicked.
                            self.stockos_connector._update_sidecar(path, {
                                "schedule_status": "needs_stockos_schedule",
                                "schedule_error": str(schedule_exc)[:1000],
                            })
                            self.emit(f"Uploaded, but weekly scheduling needs attention: {path.name}: {schedule_exc}")
                from media_pipeline import move_with_sidecar
                archived = move_with_sidecar(path, SENT_STOCKOS_DIR) if path.exists() else path
                if source_ready_path and Path(source_ready_path).exists():
                    move_with_sidecar(Path(source_ready_path), SENT_SOURCE_DIR)
                status_text = (
                    f"Sent, scheduled and archived: {archived.name}"
                    if schedule_assigned
                    else f"Sent and archived — check schedule: {archived.name}"
                )
                self.root.after(0, lambda text=status_text: self.stockos_status.set(text))
                self.emit(f"Archived after StockOS upload: {archived}")
            except Exception as exc:
                self.emit(f"StockOS upload failed for {path.name}: {exc}")
                self.root.after(0, lambda p=path: self.stockos_status.set(f"Upload failed: {p.name}"))
            finally:
                with self.stockos_enqueued_lock:
                    self.stockos_enqueued.discard(path)
                self.stockos_upload_queue.task_done()

    def show_dashboard(self):
        def count_videos(folder):
            return sum(1 for path in folder.rglob("*")
                       if path.is_file() and path.suffix.lower() in VIDEO_EXTS)

        queue_counts = {}
        for item in self.tree.get_children():
            state = self.tree.set(item, "status") or "queued"
            queue_counts[state] = queue_counts.get(state, 0) + 1
        usage = shutil.disk_usage(BASE)
        lines = [
            f"Ready: {count_videos(READY_DIR)}",
            f"Needs review: {count_videos(NEEDS_REVIEW_DIR)}",
            f"Needs trim: {count_videos(NEEDS_TRIM_DIR)}",
            f"StockOS pending: {count_videos(STOCKOS_PENDING_DIR)}",
            f"Sent to StockOS: {count_videos(SENT_STOCKOS_DIR)}",
            f"Music clips: {len(self.music_files())}",
            f"Low resolution: {count_videos(REJECTED_DIR)}",
            f"Too short: {count_videos(REJECTED_SHORT_DIR)}",
            "",
            "Source library:",
        ]
        lines.extend(f"  {name}: {count_videos(folder)}" for name, folder in PLATFORM_DIRS.items())
        lines += ["", "Queue:"]
        lines.extend(f"  {state}: {count}" for state, count in sorted(queue_counts.items()))
        lines += ["", f"Free disk space: {usage.free / (1024 ** 3):.1f} GB"]
        messagebox.showinfo("Hair Tutorial Dashboard", "\n".join(lines))

    def brand_video_dialog(self):
        files = self.choose_videos_for_editing()
        if files:
            threading.Thread(target=self.process_video_copies, args=(files, "brand"), daemon=True).start()

    def clean_video_dialog(self):
        if not messagebox.askyesno(
            "Remove detected text",
            "OCR removal is slower and may affect hair or hands behind text.\n"
            "Original files will be kept. Continue?",
        ):
            return
        files = self.choose_videos_for_editing()
        if files:
            threading.Thread(target=self.process_video_copies, args=(files, "remove"), daemon=True).start()

    def cover_video_dialog(self):
        files = self.choose_videos_for_editing()
        if files:
            threading.Thread(target=self.process_video_copies, args=(files, "cover"), daemon=True).start()

    def text_only_video_dialog(self):
        files = self.choose_videos_for_editing()
        if files:
            threading.Thread(target=self.process_video_copies, args=(files, "text"), daemon=True).start()

    def process_video_copies(self, files, mode):
        if self.cleaning_active.is_set():
            self.emit("A video editing job is already running")
            return
        self.cleaning_active.set()
        total = len(files)
        completed = 0
        failures = []
        try:
            from video_cleaner import (audit_unexpected_text, brand_video, clean_video,
                                       clean_english_text_video, cover_text_video,
                                       scan_reuse_restrictions)
            from media_pipeline import inspect_video, unique_path, with_duration_in_name
            mode_label = {"remove": "OCR text removal + branding",
                          "cover": "English text cover + branding",
                          "text": "OCR removal + English text + branding",
                          "brand": "fast branding"}.get(mode, mode)
            self.emit(f"Starting {mode_label} for {total} video(s)")
            self.set_progress(0, total, f"Editing 0/{total}")
            for index, filename in enumerate(files):
                source = Path(filename)
                suffix = {"remove": "_BUUBLE_clean", "cover": "_BUUBLE_cover",
                          "text": "_BUUBLE_text"}.get(mode, "_BUUBLE")
                source_info = inspect_video(source)
                destination_name = with_duration_in_name(
                    Path(f"{safe_name(source.stem)}{suffix}.mp4"),
                    source_info.get("duration_seconds"),
                )
                destination = unique_path(PROCESSING_DIR / destination_name.name)
                try:
                    if mode in ("remove", "cover", "text"):
                        rights_hits = scan_reuse_restrictions(source)
                        if rights_hits:
                            rights_report = unique_path(
                                NEEDS_REVIEW_DIR / f"{safe_name(source.stem)}_RIGHTS_REVIEW.json"
                            )
                            rights_report.write_text(json.dumps({
                                "source_file": str(source),
                                "pipeline_status": "rights-review",
                                "reason": "Explicit no-repost or permission warning detected",
                                "detected_text": rights_hits,
                            }, ensure_ascii=False, indent=2), encoding="utf-8")
                            raise RuntimeError(
                                f"Rights warning detected; OCR removal was stopped. Review {rights_report.name}"
                            )
                        def frame_progress(done, frame_total, base=index):
                            fraction = done / max(1, frame_total)
                            self.set_progress(base + fraction, total, f"Text processing {base + 1}/{total}")
                        if mode == "cover":
                            cover_text_video(
                                source, destination, self.english_headline.get(),
                                self.brand_text.get(), self.brand_website.get(),
                                progress=frame_progress, mute_audio=self.mute_audio.get(),
                                use_panels=True,
                            )
                            hits = audit_unexpected_text(destination, non_ascii_only=True)
                        elif mode == "text":
                            clean_english_text_video(
                                source, destination, self.english_headline.get(),
                                self.brand_text.get(), self.brand_website.get(),
                                progress=frame_progress, position=self.brand_position.get(),
                                mute_audio=self.mute_audio.get(),
                            )
                            hits = audit_unexpected_text(destination, non_ascii_only=True)
                        else:
                            clean_video(source, destination, self.brand_text.get(),
                                        self.brand_website.get(), progress=frame_progress,
                                        position=self.brand_position.get(), mute_audio=self.mute_audio.get())
                            hits = audit_unexpected_text(destination)
                        target_dir = NEEDS_REVIEW_DIR if hits else READY_DIR
                        if hits:
                            report = destination.with_suffix(destination.suffix + ".ocr.json")
                            report.write_text(json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")
                    else:
                        brand_video(source, destination, self.brand_text.get(),
                                    self.brand_website.get(), self.brand_position.get(),
                                    mute_audio=self.mute_audio.get())
                        hits = []
                        target_dir = NEEDS_REVIEW_DIR
                    final_path = unique_path(target_dir / destination.name)
                    shutil.move(str(destination), str(final_path))
                    report = destination.with_suffix(destination.suffix + ".ocr.json")
                    if report.exists():
                        shutil.move(str(report), str(final_path.with_suffix(final_path.suffix + ".ocr.json")))
                    completed += 1
                    self.set_progress(index + 1, total, f"Edited {index + 1}/{total}")
                    state = "Needs Review" if target_dir == NEEDS_REVIEW_DIR else "Ready"
                    self.emit(f"Created branded copy -> {state}: {final_path.name}")
                except Exception as exc:
                    failures.append(f"{source.name}: {exc}")
                    self.emit(f"Video editing failed for {source.name}: {exc}")
            summary = (f"Created: {completed}\nFailed: {len(failures)}\n"
                       f"Approved files: {READY_DIR}\nReview files: {NEEDS_REVIEW_DIR}")
            self.set_progress(total, total, "Editing finished")
            self.root.after(0, lambda: messagebox.showinfo("Video editing finished", summary))
        finally:
            self.cleaning_active.clear()

    def dismiss_login_popup(self, page):
        """Close ordinary page login overlays; never handles CAPTCHA or permission dialogs."""
        selectors = [
            "[class*='login'] [class*='close']",
            "[class*='Login'] [class*='close']",
            "[class*='modal'] [class*='close']",
            "[role='dialog'] button[aria-label*='Close']",
            "[role='dialog'] button[aria-label*='close']",
            "[role='dialog'] button:has-text('×')",
            "[role='dialog'] button:has-text('关闭')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=300):
                    locator.click(timeout=1500)
                    self.emit("Closed a website login popup")
                    page.wait_for_timeout(500)
                    return True
            except Exception:
                pass
        return False

    def search_xhs_browser(self):
        topic = self.keyword.get().strip()
        if not topic:
            messagebox.showinfo("Keywords required", "Enter a topic or keywords first.")
            return
        if sync_playwright is None:
            messagebox.showerror("Browser component missing", "The private-browser component is not installed.")
            return
        threading.Thread(target=self.search_xhs_browser_worker,
                         args=(topic, int(self.target_count.get())), daemon=True).start()

    def search_xhs_browser_worker(self, topic, target):
        downloaded = self.downloaded_urls()
        existing = {self.normalize_url(self.tree.set(i, "url")) for i in self.tree.get_children()}
        known_urls = set(downloaded) | existing
        known_keys = {self.video_key(url) for url in known_urls if self.video_key(url)}
        known_keys.update(self.disk_video_keys())
        collected = self.collect_xhs_urls(topic, target, known_urls, known_keys)
        if collected is None:
            return
        accepted = []
        duplicate_count = 0
        for url in collected:
            if self.candidate_is_known(url, known_urls, known_keys):
                duplicate_count += 1
                continue
            accepted.append(self.remember_candidate(url, known_urls, known_keys))
            if len(accepted) >= target:
                break
        def add_results():
            items = []
            for url in accepted:
                items.append(self.tree.insert("", "end", values=self.queue_values("Xiaohongshu", url)))
            self.save_queue()
            self.emit(f"REDnote scan: {len(collected)} URL(s), {duplicate_count} known, "
                      f"{len(accepted)}/{target} new queued")
            if self.auto_download.get() and items:
                threading.Thread(target=self.batch_download_worker, args=(items,), daemon=True).start()
            elif items:
                messagebox.showinfo("REDnote search finished", f"Queued {len(items)} new URL(s).")
            else:
                messagebox.showinfo("REDnote search finished", "No new REDnote URLs were found.")
        self.root.after(0, add_results)

    def collect_xhs_urls(self, topic, target, excluded_urls=None, excluded_keys=None):
        chrome_candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((p for p in chrome_candidates if p.exists()), None)
        if not chrome:
            self.emit("Google Chrome was not found")
            return None
        profile = APP_DIR / "xhs_browser_profile"
        search_url = "https://www.rednote.com/search_result?" + urllib.parse.urlencode({
            "keyword": topic, "source": "web_explore_feed", "type": "51",
        })
        collected = []
        excluded_urls = set(excluded_urls or ())
        excluded_keys = set(excluded_keys or ())
        self.emit("Opening REDnote directly. If requested, log in or scan the QR code in Chrome.")
        try:
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(profile), executable_path=str(chrome), headless=False,
                    locale="zh-CN", viewport={"width": 1280, "height": 850},
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                self.dismiss_login_popup(page)
                # Keep the window available for login, then collect visible public note links.
                unchanged_rounds = 0
                previous_count = 0
                for _ in range(40):
                    page.wait_for_timeout(2500)
                    self.dismiss_login_popup(page)
                    try:
                        hrefs = page.locator(
                            "a[href*='/explore/'], a[href*='/discovery/item/'], a[href*='/search_result/']"
                        ).evaluate_all(
                            "els => els.map(e => e.href)"
                        )
                        for href in hrefs:
                            if not re.search(r"/(?:explore|discovery/item|search_result)/[0-9a-f]{20,}", href, re.I):
                                continue
                            clean = self.normalize_url(href)
                            if clean and clean not in collected:
                                collected.append(clean)
                        fresh = [url for url in collected
                                 if not self.candidate_is_known(url, excluded_urls, excluded_keys)]
                        if len(fresh) >= target:
                            break
                        unchanged_rounds = unchanged_rounds + 1 if len(collected) == previous_count else 0
                        previous_count = len(collected)
                        if unchanged_rounds >= 8:
                            break
                        page.mouse.wheel(0, 2200)
                    except Exception:
                        pass
                context.close()
        except Exception as exc:
            self.emit(f"REDnote browser search failed: {exc}")
            return None
        # One REDnote card can expose both a tokenless URL and a usable token URL.
        # Keep one URL per post ID and prefer the URL with the longest query token.
        best = {}
        for url in collected:
            key = self.video_key(url) or url
            if key not in best or len(urllib.parse.urlsplit(url).query) > len(urllib.parse.urlsplit(best[key]).query):
                best[key] = url
        return list(best.values())

    def collect_douyin_urls(self, topic, target, excluded_urls=None, excluded_keys=None):
        chrome_candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((p for p in chrome_candidates if p.exists()), None)
        if not chrome:
            return None
        profile = APP_DIR / "browser_profile"
        search_url = "https://www.douyin.com/search/" + urllib.parse.quote(topic)
        collected = []
        api_ids = set()
        excluded_urls = set(excluded_urls or ())
        excluded_keys = set(excluded_keys or ())
        self.emit("Opening Douyin search directly with the saved browser session...")
        try:
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(profile), executable_path=str(chrome), headless=False,
                    locale="zh-CN", viewport={"width": 1280, "height": 850},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = context.pages[0] if context.pages else context.new_page()

                def scan_ids(value):
                    if isinstance(value, dict):
                        aweme_id = value.get("aweme_id")
                        if isinstance(aweme_id, str) and aweme_id.isdigit():
                            api_ids.add(aweme_id)
                        for child in value.values():
                            scan_ids(child)
                    elif isinstance(value, list):
                        for child in value:
                            scan_ids(child)

                def handle_response(response):
                    try:
                        if "search" in response.url and "application/json" in (response.headers.get("content-type") or ""):
                            scan_ids(response.json())
                    except Exception:
                        pass

                page.on("response", handle_response)
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                self.dismiss_login_popup(page)
                unchanged_rounds = 0
                previous_count = 0
                for _ in range(40):
                    page.wait_for_timeout(2500)
                    self.dismiss_login_popup(page)
                    try:
                        hrefs = page.locator("a[href*='/video/']").evaluate_all("els => els.map(e => e.href)")
                        for href in hrefs:
                            if not re.search(r"/video/\d+", href):
                                continue
                            clean = self.normalize_url(href)
                            if clean not in collected:
                                collected.append(clean)
                        for aweme_id in api_ids:
                            direct = f"https://www.douyin.com/video/{aweme_id}"
                            if direct not in collected:
                                collected.append(direct)
                        fresh = [url for url in collected
                                 if not self.candidate_is_known(url, excluded_urls, excluded_keys)]
                        if len(fresh) >= target:
                            break
                        unchanged_rounds = unchanged_rounds + 1 if len(collected) == previous_count else 0
                        previous_count = len(collected)
                        if unchanged_rounds >= 8:
                            break
                        page.mouse.wheel(0, 2200)
                    except Exception:
                        pass
                context.close()
        except Exception as exc:
            self.emit(f"Douyin direct browser search failed: {exc}")
            return None
        return collected

    def download_selected(self):
        item = self.selected_item()
        if not item:
            return
        threading.Thread(target=self.batch_download_worker, args=([item],), daemon=True).start()

    def auto_find(self):
        topic = self.keyword.get().strip()
        if not topic:
            messagebox.showinfo("Keywords required", "Enter a topic or keywords first.")
            return
        if DDGS is None:
            messagebox.showerror("Search component missing", "The DDGS search component is not installed.")
            return
        platforms = self.selected_platforms()
        if not platforms:
            messagebox.showinfo("Select a platform", "Select at least one platform.")
            return
        threading.Thread(target=self.auto_find_worker, args=(topic, int(self.target_count.get()), platforms), daemon=True).start()

    def selected_platforms(self):
        return [name for name, var in self.platform_vars.items() if var.get()]

    def detect_platform(self, url):
        host = urllib.parse.urlparse(url).netloc.lower()
        if "douyin.com" in host:
            return "Douyin"
        if "xiaohongshu.com" in host or "xhslink.com" in host or "rednote.com" in host:
            return "Xiaohongshu"
        if "bilibili.com" in host or "b23.tv" in host:
            return "Bilibili"
        return None

    def score_result(self, title, url):
        text = (title + " " + url).lower()
        return sum(2 if term in text else 0 for term in TUTORIAL_TERMS)

    def auto_find_worker(self, topic, target, platforms):
        self.emit(f"Automatic research started: {topic}")
        found = []
        seen = {self.normalize_url(self.tree.set(i, "url")) for i in self.tree.get_children()}
        seen.update(self.downloaded_urls())
        seen_keys = {self.video_key(url) for url in seen if self.video_key(url)}
        seen_keys.update(self.disk_video_keys())
        for platform in platforms:
            remaining = target
            if platform == "Douyin":
                urls = self.collect_douyin_urls(topic, target, seen, seen_keys)
                accepted = []
                duplicate_count = 0
                for url in urls or []:
                    if self.candidate_is_known(url, seen, seen_keys):
                        duplicate_count += 1
                        continue
                    clean = self.remember_candidate(url, seen, seen_keys)
                    accepted.append(("Douyin", clean, "queued"))
                    if len(accepted) >= target:
                        break
                self.emit(f"Douyin scan: {len(urls or [])} URL(s), {duplicate_count} known, "
                          f"{len(accepted)}/{target} new")
                if accepted:
                    found.extend(accepted)
                    self.emit(f"Douyin: found {len(accepted)} result URL(s) directly in the browser")
                    remaining -= len(accepted)
                    if remaining <= 0:
                        continue
                self.emit(f"Douyin: searching public results for {remaining} more new URL(s)")
            if platform == "Xiaohongshu":
                urls = self.collect_xhs_urls(topic, target, seen, seen_keys)
                accepted = []
                duplicate_count = 0
                for url in urls or []:
                    if self.candidate_is_known(url, seen, seen_keys):
                        duplicate_count += 1
                        continue
                    clean = self.remember_candidate(url, seen, seen_keys)
                    accepted.append(("Xiaohongshu", clean, "queued"))
                    if len(accepted) >= target:
                        break
                found.extend(accepted)
                self.emit(f"REDnote scan: {len(urls or [])} URL(s), {duplicate_count} known, "
                          f"{len(accepted)}/{target} new")
                self.emit(f"REDnote: found {len(accepted)} result URL(s) directly in the logged-in browser")
                remaining -= len(accepted)
                if remaining <= 0:
                    continue
                self.emit(f"REDnote: searching public results for {remaining} more new URL(s)")
            if platform == "Bilibili":
                accepted = self.search_bilibili(topic, target, seen, seen_keys)
                found.extend(accepted)
                self.emit(f"Bilibili: found {len(accepted)} tutorial candidate(s)")
                continue
            domain = SEARCH_DOMAINS[platform]
            queries = [
                f'site:{domain} "{topic}"',
                f'site:{domain} 抓夹 发型 教程',
                f'site:{domain} 鲨鱼夹 用法 教程',
            ]
            if platform == "Xiaohongshu":
                queries += [
                    f'site:xiaohongshu.com "{topic}"',
                    'site:xiaohongshu.com 抓夹 盘发 教程',
                    'site:xiaohongshu.com 鲨鱼夹 发型 教程',
                ]
            candidates = []
            try:
                with DDGS(timeout=20) as search:
                    for query in queries:
                        query_results = []
                        last_error = None
                        for backend in (("google", "brave", "duckduckgo") if platform == "Xiaohongshu" else ("auto",)):
                            try:
                                query_results = search.text(query, max_results=max(remaining * 4, 40), backend=backend)
                                if query_results:
                                    break
                            except Exception as exc:
                                last_error = exc
                        if not query_results and last_error:
                            self.emit(f"{platform}: one search source returned no results; trying the next query")
                            continue
                        for result in query_results:
                            url = result.get("href") or result.get("url") or ""
                            title = result.get("title") or ""
                            description = result.get("body") or result.get("description") or ""
                            searchable = title + " " + description
                            clean = self.normalize_url(url)
                            if not url.startswith("http") or self.candidate_is_known(clean, seen, seen_keys):
                                continue
                            if platform == "Douyin" and "/video/" not in url:
                                continue
                            if platform == "Bilibili" and "/video/" not in url:
                                continue
                            if platform == "Xiaohongshu" and not any(x in url for x in ("/explore/", "/discovery/item/")):
                                continue
                            candidates.append((self.score_result(searchable, clean), title, clean))
                candidates.sort(key=lambda x: (-x[0], x[1]))
                accepted = []
                for score, title, url in candidates:
                    if self.candidate_is_known(url, seen, seen_keys) or score < 2:
                        continue
                    clean = self.remember_candidate(url, seen, seen_keys)
                    accepted.append((platform, clean, "queued"))
                    if len(accepted) >= remaining:
                        break
                found.extend(accepted)
                if platform == "Xiaohongshu" and not accepted:
                    self.emit("Xiaohongshu: no relevant public indexed URLs found; this is a discovery limitation, not a download failure")
                else:
                    self.emit(f"{platform}: found {len(accepted)} tutorial candidate(s)")
            except Exception as exc:
                self.emit(f"{platform} search error: {exc}")
        def add_to_ui():
            items = []
            for platform, url, status in found:
                items.append(self.tree.insert("", "end", values=self.queue_values(platform, url, status)))
            self.save_queue()
            counts = {platform: sum(1 for row in found if row[0] == platform)
                      for platform in platforms}
            result_text = ", ".join(f"{name} {counts[name]}/{target}" for name in platforms)
            self.emit(f"Research finished: {len(items)} new URL(s) queued ({result_text})")
            short = [name for name in platforms if counts[name] < target]
            if short:
                self.emit("Search was exhausted before reaching the new-video target for: " + ", ".join(short))
            if self.auto_download.get() and items:
                threading.Thread(target=self.batch_download_worker, args=(items,), daemon=True).start()
            elif items:
                messagebox.showinfo("Research finished", f"Found and queued {len(items)} new URL(s).\n{result_text}")
            else:
                messagebox.showinfo(
                    "Research finished",
                    "No new URLs were queued. Results may already be downloaded, filtered, or unavailable.",
                )
        self.root.after(0, add_to_ui)

    def search_bilibili(self, topic, target, seen, seen_keys):
        """Use Bilibili's public search endpoint instead of relying on web indexing."""
        accepted = []
        keywords = [topic, "抓夹发型教程", "鲨鱼夹盘发教程"]
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://search.bilibili.com/"}
        for keyword in keywords:
            for page in range(1, 11):
                endpoint = "https://api.bilibili.com/x/web-interface/wbi/search/type?" + urllib.parse.urlencode({
                    "search_type": "video", "keyword": keyword, "page": page,
                })
                try:
                    req = urllib.request.Request(endpoint, headers=headers)
                    with urllib.request.urlopen(req, timeout=20) as response:
                        payload = json.load(response)
                    results = (payload.get("data") or {}).get("result") or []
                    if not results:
                        break
                    for result in results:
                        bvid = result.get("bvid")
                        title = re.sub(r"<[^>]+>", "", html.unescape(result.get("title") or ""))
                        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
                        if (not url or self.candidate_is_known(url, seen, seen_keys)
                                or self.score_result(title, url) < 2):
                            continue
                        clean = self.remember_candidate(url, seen, seen_keys)
                        accepted.append(("Bilibili", clean, "queued"))
                        if len(accepted) >= target:
                            return accepted
                except Exception as exc:
                    self.emit(f"Bilibili API warning (page {page}): {exc}")
                    break
        return accepted

    def batch_download_worker(self, items):
        if self.batch_active.is_set():
            self.emit("A download batch is already running")
            return
        self.batch_active.set()
        self.stop_after_current.clear()
        total = len(items)
        progress = {"completed": 0}
        progress_lock = threading.Lock()
        self.set_progress(0, total, f"Downloading 0/{total}")

        def run_group(group):
            for item in group:
                self.download_gate.wait()
                if self.stop_after_current.is_set():
                    break
                self.download_worker(item)
                with progress_lock:
                    progress["completed"] += 1
                    self.set_progress(progress["completed"], total)

        try:
            groups = {}
            for item in items:
                platform = self.tree.set(item, "platform")
                groups.setdefault(platform, []).append(item)
            if self.parallel_platforms.get() and len(groups) > 1:
                self.emit(f"Parallel mode: {len(groups)} platform worker(s), one download per platform")
                workers = [threading.Thread(target=run_group, args=(group,), daemon=True)
                           for group in groups.values()]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
            else:
                run_group(list(items))
            stopped = self.stop_after_current.is_set()
            states = [self.tree.set(item, "status") for item in items]
            done = sum(state in ("done", "already downloaded") for state in states)
            failed = sum(state in (
                "error", "browser needed", "retry needed", "site restricted",
                "no video stream", "login required", "unavailable", "needs attention",
                "low resolution") for state in states)
            queued = sum(state == "queued" for state in states)
            message = (f"Completed: {done}\nNeeds attention: {failed}\nStill queued: {queued}")
            self.emit(("Queue stopped. " if stopped else "Queue finished. ") +
                      f"Completed {done}, needs attention {failed}, queued {queued}")
            self.set_progress(progress["completed"], total,
                              "Stopped" if stopped else "Finished")
            title = "Queue stopped" if stopped else "Downloads finished"
            self.root.after(0, lambda: messagebox.showinfo(title, message))
        finally:
            self.batch_active.clear()

    def file_digest(self, path):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def remove_exact_duplicate(self, new_files):
        """Remove only a just-created byte-identical duplicate, never an older file."""
        older = [path for folder in PLATFORM_DIRS.values() if folder.exists()
                 for path in folder.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTS
                 and path not in new_files]
        known = {}
        for path in older:
            try:
                known.setdefault((path.stat().st_size, self.file_digest(path)), path)
            except Exception:
                pass
        removed = 0
        for path in new_files:
            try:
                key = (path.stat().st_size, self.file_digest(path))
                if key in known:
                    path.unlink()
                    removed += 1
                    self.emit(f"Removed exact duplicate; kept the earlier file: {known[key].name}")
                else:
                    known[key] = path
            except Exception:
                pass
        return removed

    def enforce_minimum_resolution(self, files):
        try:
            import cv2
        except Exception:
            return list(files), []
        minimum = max(1, int(self.min_short_edge.get()))
        kept, rejected = [], []
        for path in files:
            if path.suffix.lower() not in VIDEO_EXTS:
                continue
            capture = cv2.VideoCapture(str(path))
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            capture.release()
            if width and height and min(width, height) < minimum:
                destination = REJECTED_DIR / path.name
                counter = 2
                while destination.exists():
                    destination = REJECTED_DIR / f"{path.stem}_{counter}{path.suffix}"
                    counter += 1
                shutil.move(str(path), str(destination))
                rejected.append((destination, width, height))
                self.emit(f"Rejected low resolution {width}x{height}: {destination.name}")
            else:
                kept.append(path)
        return kept, rejected

    def prepare_downloaded_copy(self, source, source_status, metadata, item=None):
        """Create and audit one publishable copy while always keeping the source."""
        from cover_generator import generate_cover
        from media_pipeline import inspect_video, unique_path, with_duration_in_name, write_metadata
        from video_cleaner import (audit_unexpected_text, clean_english_text_video,
                                   clean_video, cover_text_video,
                                   scan_reuse_restrictions)

        with self.pipeline_lock:
            if item:
                self.tree.set(item, "status", "OCR processing")
            output_name = source.name.replace("_SRC", "_BUUBLE")
            if output_name == source.name:
                output_name = f"{source.stem}_BUUBLE.mp4"
            duration = metadata.get("duration_seconds")
            if not isinstance(duration, (int, float)):
                duration = inspect_video(source).get("duration_seconds")
            output_name = with_duration_in_name(
                Path(output_name).with_suffix(".mp4"), duration
            ).name
            working = unique_path(PROCESSING_DIR / output_name)
            selected_mode = self.text_mode.get()
            cover_mode = selected_mode == "Cover with English"
            text_only_mode = selected_mode == "Remove OCR + English Text"
            mode_label = "OCR removal + English text" if text_only_mode else ("English cover" if cover_mode else "OCR removal")
            self.emit(f"Preparing publishable copy with {mode_label}: {source.name}")
            try:
                rights_hits = scan_reuse_restrictions(source)
                if rights_hits:
                    rights_report = unique_path(
                        NEEDS_REVIEW_DIR / f"{safe_name(source.stem)}_RIGHTS_REVIEW.json"
                    )
                    rights_payload = {
                        "source_file": str(source),
                        "pipeline_status": "rights-review",
                        "reason": "Explicit no-repost or permission warning detected",
                        "detected_text": rights_hits,
                    }
                    rights_report.write_text(
                        json.dumps(rights_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    metadata.update({
                        "pipeline_status": "rights-review",
                        "reuse_restriction_hits": rights_hits,
                        "rights_review_report": str(rights_report),
                    })
                    write_metadata(source, metadata)
                    if item:
                        self.tree.set(item, "status", "rights review")
                    self.emit(
                        f"Stopped before text removal: explicit reuse warning found. "
                        f"Review {rights_report.name}"
                    )
                    return "needs-review", source
                reported_quarter = [-1]
                def pipeline_progress(done, total):
                    percent = min(100, round(done * 100 / max(1, total)))
                    self.set_progress(done, total, f"OCR {percent}%: {source.name[:28]}")
                    quarter = percent // 25
                    if quarter > reported_quarter[0]:
                        reported_quarter[0] = quarter
                        self.emit(f"OCR progress {min(100, quarter * 25)}%: {source.name}")
                if cover_mode:
                    cover_text_video(
                        source, working, self.english_headline.get(), self.brand_text.get(),
                        self.brand_website.get(), progress=pipeline_progress,
                        mute_audio=self.mute_audio.get(),
                        use_panels=True,
                    )
                elif text_only_mode:
                    clean_english_text_video(
                        source, working, self.english_headline.get(), self.brand_text.get(),
                        self.brand_website.get(), progress=pipeline_progress,
                        position=self.brand_position.get(), mute_audio=self.mute_audio.get(),
                    )
                else:
                    clean_video(
                        source, working, self.brand_text.get(), self.brand_website.get(),
                        progress=pipeline_progress, position=self.brand_position.get(),
                        mute_audio=self.mute_audio.get(),
                    )
                if item:
                    self.tree.set(item, "status", "checking text")
                hits = audit_unexpected_text(working, non_ascii_only=(cover_mode or text_only_mode))
                final_status = "needs-review" if hits or source_status == "needs-review" else "ready"
                target_dir = NEEDS_REVIEW_DIR if final_status == "needs-review" else READY_DIR
                final_path = unique_path(target_dir / working.name)
                shutil.move(str(working), str(final_path))
                edited_metadata = dict(metadata)
                edited_metadata.update({
                    "file": str(final_path),
                    "source_file": str(source),
                    "pipeline_status": final_status,
                    "unexpected_ocr_hits": hits,
                    "audio_muted": bool(self.mute_audio.get()),
                    "brand": self.brand_text.get(),
                    "brand_website": self.brand_website.get(),
                    "text_handling_mode": ("english-text-clean-first" if text_only_mode else
                                           ("cover-with-english" if cover_mode else "ocr-remove")),
                    "english_headline": self.english_headline.get() if (cover_mode or text_only_mode) else "",
                })
                cover_path = final_path.with_name(f"{final_path.stem}_COVER.jpg")
                cover_info = generate_cover(
                    final_path,
                    cover_path,
                    metadata=edited_metadata,
                    history_path=BASE / "cover_title_history.json",
                )
                edited_metadata.update({
                    "cover_file": str(cover_path),
                    "cover_headline": cover_info["headline"],
                    "cover_generator": cover_info["generator"],
                    "cover_width": cover_info["width"],
                    "cover_height": cover_info["height"],
                })
                write_metadata(final_path, edited_metadata)
                self.emit(f"Created cover: {cover_path.name} — {cover_info['headline']}")
                self.emit(f"Publishing copy -> {'Ready' if final_status == 'ready' else 'Needs Review'}: {final_path.name}")
                if final_status == "ready" and self.stockos_auto.get():
                    self.prepare_reviewed_for_stockos([final_path], [None])
                return final_status, final_path
            except Exception:
                working.unlink(missing_ok=True)
                raise

    def finalize_download(self, item, platform, url, out_dir, before_files, method, success_message):
        from media_pipeline import (build_metadata, evaluate_video, inspect_video,
                                    move_with_sidecar, rename_source, write_metadata)

        new_files = [path for path in out_dir.iterdir()
                     if path.is_file() and path.resolve() not in before_files
                     and path.suffix.lower() in VIDEO_EXTS]
        new_files, rejected = self.enforce_minimum_resolution(new_files)
        if rejected and not new_files:
            self.tree.set(item, "status", "low resolution")
            self.tree.set(item, "reason", f"Below {self.min_short_edge.get()}p minimum; choose another source")
            self.append_history(platform, url, "low-resolution")
            self.emit(f"Download finished but did not meet the {self.min_short_edge.get()}p short-edge minimum")
            return
        removed = self.remove_exact_duplicate(new_files)
        new_files = [path for path in new_files if path.exists()]
        if removed and not new_files:
            self.tree.set(item, "status", "already downloaded")
            self.tree.set(item, "reason", "Exact video file is already in the library")
            self.append_history(platform, url, "exact-duplicate")
            self.emit("Downloaded file matched an existing video and was removed")
            return

        final_states = []
        topic = self.keyword.get().strip()
        for path in new_files:
            try:
                self.tree.set(item, "status", "checking")
                if self.mute_original_audio.get():
                    from video_cleaner import mute_video_in_place
                    mute_video_in_place(path)
                    self.emit(f"Removed audio from downloaded source: {path.name}")
                info = inspect_video(path)
                source, category, style = rename_source(path, platform, url, topic, info)
                state, reasons = evaluate_video(
                    info, max(1, int(self.min_short_edge.get())),
                    max(1, int(self.min_duration.get())), max(2, int(self.max_duration.get())),
                )
                metadata = build_metadata(source, platform, url, topic, info,
                                          category, style, state, reasons)
                metadata["audio_muted"] = bool(self.mute_original_audio.get())
                write_metadata(source, metadata)
                if state == "too-short":
                    source = move_with_sidecar(source, REJECTED_SHORT_DIR)
                    metadata["file"] = str(source)
                    write_metadata(source, metadata)
                    self.emit(f"Rejected video shorter than {self.min_duration.get()} seconds: {source.name}")
                elif state == "needs-trim":
                    source = move_with_sidecar(source, NEEDS_TRIM_DIR)
                    metadata["file"] = str(source)
                    write_metadata(source, metadata)
                    self.emit(f"Video needs trimming to {self.max_duration.get()} seconds or less: {source.name}")
                elif self.auto_prepare.get():
                    state, _ = self.prepare_downloaded_copy(source, state, metadata, item=item)
                final_states.append(state)
            except Exception as exc:
                final_states.append("needs-review")
                self.emit(f"Post-download inspection failed for {path.name}: {exc}")

        priority = ("needs-review", "needs-trim", "too-short", "ready")
        overall = next((state for state in priority if state in final_states), "done")
        self.tree.set(item, "status", overall)
        self.tree.set(item, "reason", "" if final_states else "Download returned no new video file")
        self.append_history(platform, url, method)
        self.emit(f"{success_message}; pipeline status: {overall}")

    def download_worker(self, item):
        platform = self.tree.set(item, "platform")
        url = self.tree.set(item, "url")
        category = self.tree.set(item, "category")
        if self.normalize_url(url) in self.downloaded_urls() or self.video_already_on_disk(url):
            self.tree.set(item, "status", "already downloaded")
            self.tree.set(item, "reason", "URL or video file is already in download history")
            self.emit(f"Skipped duplicate: {url}")
            self.save_queue()
            return
        out_dir = self.category_download_dir(platform, category)
        before_files = {path.resolve() for path in out_dir.iterdir() if path.is_file()}
        python = sys.executable
        env = os.environ.copy()
        vendor = APP_DIR / "vendor"
        env["PYTHONPATH"] = str(vendor)
        template = str(out_dir / "%(title).80s [%(id)s].%(ext)s")
        cmd = [python, "-m", "yt_dlp", "--windows-filenames", "--no-playlist",
               "-S", "res:1080,fps", "-o", template]
        xhs_profile = APP_DIR / "xhs_browser_profile"
        if platform == "Xiaohongshu" and xhs_profile.exists():
            cmd += ["--cookies-from-browser", f"chrome:{xhs_profile}"]
        elif self.use_cookies.get():
            cmd += ["--cookies-from-browser", "chrome:Default"]
        cmd.append(url)
        self.tree.set(item, "status", "downloading")
        self.tree.set(item, "reason", "")
        self.emit(f"Downloading from {platform}...")
        try:
            proc = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=900,
                                  creationflags=NO_WINDOW)
            if (proc.returncode != 0 and platform == "Bilibili" and
                    any(marker in (proc.stderr or "").casefold()
                        for marker in ("bytes read", "more expected", "incomplete read"))):
                self.emit("Bilibili transfer stopped early; resuming with smaller chunks...")
                retry_cmd = cmd[:-1] + ["--continue", "--http-chunk-size", "1M",
                                        "--retries", "15", "--fragment-retries", "15", url]
                proc = subprocess.run(retry_cmd, env=env, text=True, capture_output=True,
                                      timeout=900, creationflags=NO_WINDOW)
            if proc.returncode == 0:
                self.finalize_download(item, platform, url, out_dir, before_files,
                                       "yt-dlp", "Download completed")
            else:
                last = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
                detail = last[0] if last else ""
                browser_ok, browser_reason = False, ""
                if platform == "Douyin":
                    browser_ok, browser_reason = self.download_douyin_browser(url, out_dir)
                elif platform == "Xiaohongshu":
                    browser_ok, browser_reason = self.download_rednote_browser(url, out_dir)
                if browser_ok and platform == "Douyin":
                    self.finalize_download(item, platform, url, out_dir, before_files,
                                           "private-browser", "Douyin download completed with the built-in private browser")
                elif browser_ok and platform == "Xiaohongshu":
                    self.finalize_download(item, platform, url, out_dir, before_files,
                                           "rednote-browser", "REDnote download completed with the saved browser session")
                else:
                    status, reason = self.classify_download_issue(platform, detail, browser_reason)
                    self.tree.set(item, "status", status)
                    self.tree.set(item, "reason", reason)
                    self.emit(f"{platform}: {reason}. Detail: {detail}")
        except Exception as exc:
            status, reason = self.classify_download_issue(platform, str(exc))
            self.tree.set(item, "status", status)
            self.tree.set(item, "reason", reason)
            self.emit(f"Download error: {exc}")
        self.save_queue()

    def download_rednote_browser(self, url, out_dir):
        if sync_playwright is None or requests is None:
            return False, "Private-browser components are not installed"
        chrome_candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((p for p in chrome_candidates if p.exists()), None)
        if not chrome:
            return False, "Google Chrome was not found"
        profile = APP_DIR / "xhs_browser_profile"
        video_id = self.video_key(url) or datetime.now().strftime("%Y%m%d_%H%M%S")
        captured = {"media": None, "title": f"rednote_{video_id}"}

        def handle_response(response):
            try:
                content_type = (response.headers.get("content-type") or "").lower()
                media_url = response.url
                if content_type.startswith("video/") or "sns-video" in media_url or ".mp4" in media_url.lower():
                    captured["media"] = media_url
            except Exception:
                pass

        try:
            self.emit("Trying REDnote with the saved private-browser session...")
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(profile), executable_path=str(chrome), headless=True,
                    locale="zh-CN", viewport={"width": 1280, "height": 850},
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.on("response", handle_response)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                self.dismiss_login_popup(page)
                page.wait_for_timeout(12000)
                try:
                    title = page.locator("meta[property='og:title']").get_attribute("content")
                    captured["title"] = title or page.title() or captured["title"]
                except Exception:
                    pass
                cookies = {c["name"]: c["value"] for c in context.cookies()}
                try:
                    user_agent = page.evaluate("navigator.userAgent")
                except Exception:
                    user_agent = "Mozilla/5.0"
                context.close()
            if not captured["media"]:
                self.emit("REDnote page opened but no public video stream was detected")
                return False, "Page opened but did not expose a public video stream"
            destination = out_dir / (safe_name(captured["title"])[:75] + f" [{video_id}].mp4")
            with requests.get(captured["media"], headers={"User-Agent": user_agent, "Referer": url},
                              cookies=cookies, stream=True, timeout=90) as response:
                response.raise_for_status()
                with destination.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            output.write(chunk)
            if destination.exists() and destination.stat().st_size > 100000:
                return True, ""
            return False, "Browser download returned an empty or incomplete file"
        except Exception as exc:
            self.emit(f"REDnote private-browser fallback failed: {exc}")
            return False, f"Browser attempt failed: {str(exc)[:90]}"

    def download_douyin_browser(self, url, out_dir):
        """Create fresh anonymous cookies and capture Douyin's public detail response."""
        if sync_playwright is None or requests is None:
            self.emit("Private-browser component is unavailable")
            return False, "Private-browser components are not installed"
        video_id_match = re.search(r"/video/(\d+)", url)
        video_id = video_id_match.group(1) if video_id_match else datetime.now().strftime("%Y%m%d_%H%M%S")
        profile = APP_DIR / "browser_profile"
        chrome_candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        chrome = next((p for p in chrome_candidates if p.exists()), None)
        if not chrome:
            self.emit("Google Chrome was not found")
            return False, "Google Chrome was not found"
        captured = {"media": None, "title": f"douyin_{video_id}"}

        def handle_response(response):
            try:
                if "/aweme/v1/web/aweme/detail/" not in response.url:
                    return
                data = response.json()
                aweme = data.get("aweme_detail") or {}
                desc = aweme.get("desc") or captured["title"]
                video = aweme.get("video") or {}
                candidates = []
                for variant in video.get("bit_rate") or []:
                    play = variant.get("play_addr") or {}
                    pixels = (play.get("width") or variant.get("width") or 0) * (play.get("height") or variant.get("height") or 0)
                    bitrate = variant.get("bit_rate") or 0
                    for media_url in play.get("url_list") or []:
                        candidates.append((pixels, bitrate, media_url))
                for key in ("play_addr", "play_addr_265", "download_addr"):
                    play = video.get(key) or {}
                    pixels = (play.get("width") or video.get("width") or 0) * (play.get("height") or video.get("height") or 0)
                    for media_url in play.get("url_list") or []:
                        candidates.append((pixels, 0, media_url))
                if candidates:
                    captured["media"] = max(candidates, key=lambda item: (item[0], item[1]))[2]
                    captured["title"] = desc
            except Exception:
                pass

        try:
            self.emit("Douyin requires fresh cookies; trying the built-in private browser...")
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(profile), executable_path=str(chrome), headless=True,
                    locale="zh-CN", viewport={"width": 1280, "height": 800},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.on("response", handle_response)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                self.dismiss_login_popup(page)
                page.wait_for_timeout(8000)
                cookies = {c["name"]: c["value"] for c in context.cookies()}
                try:
                    user_agent = page.evaluate("navigator.userAgent")
                except Exception:
                    user_agent = "Mozilla/5.0"
                context.close()
            if not captured["media"]:
                self.emit("Douyin did not expose a downloadable media URL (login/CAPTCHA may be active)")
                return False, "Page did not expose video; login or CAPTCHA may be active"
            filename = safe_name(captured["title"])[:75] + f" [{video_id}].mp4"
            destination = out_dir / filename
            with requests.get(captured["media"], headers={"User-Agent": user_agent, "Referer": url},
                              cookies=cookies, stream=True, timeout=90) as response:
                response.raise_for_status()
                with destination.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            output.write(chunk)
            if destination.exists() and destination.stat().st_size > 100000:
                return True, ""
            return False, "Browser download returned an empty or incomplete file"
        except Exception as exc:
            self.emit(f"Private-browser fallback failed: {exc}")
            return False, f"Browser attempt failed: {str(exc)[:90]}"

    def append_history(self, platform, url, method):
        new = not HISTORY_FILE.exists()
        with HISTORY_FILE.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            if new:
                writer.writerow(["time", "platform", "url", "method"])
            writer.writerow([datetime.now().isoformat(timespec="seconds"), platform, url, method])

    def start_watcher(self):
        if getattr(self, "watch_thread", None) and self.watch_thread.is_alive():
            self.emit("Watcher is already running")
            return
        self.stop_watch.clear()
        self.watch_thread = threading.Thread(target=self.watch_worker, daemon=True)
        self.watch_thread.start()
        self.emit("Watching C:\\E\\HairTutorial for new browser downloads")

    def process_browser_download(self, path, platform, url=""):
        from media_pipeline import (build_metadata, evaluate_video, inspect_video,
                                    move_with_sidecar, rename_source, write_metadata)

        kept, rejected = self.enforce_minimum_resolution([path])
        if rejected or not kept:
            return "low-resolution"
        if self.remove_exact_duplicate(kept):
            return "already-downloaded"
        path = kept[0]
        if self.mute_original_audio.get():
            from video_cleaner import mute_video_in_place
            mute_video_in_place(path)
            self.emit(f"Removed audio from browser download: {path.name}")
        info = inspect_video(path)
        path, category, style = rename_source(path, platform, url, self.keyword.get(), info)
        state, reasons = evaluate_video(
            info, max(1, int(self.min_short_edge.get())),
            max(1, int(self.min_duration.get())), max(2, int(self.max_duration.get())),
        )
        metadata = build_metadata(path, platform, url, self.keyword.get(), info,
                                  category, style, state, reasons)
        metadata["audio_muted"] = bool(self.mute_original_audio.get())
        write_metadata(path, metadata)
        if state == "too-short":
            path = move_with_sidecar(path, REJECTED_SHORT_DIR)
            metadata["file"] = str(path)
            write_metadata(path, metadata)
        elif state == "needs-trim":
            path = move_with_sidecar(path, NEEDS_TRIM_DIR)
            metadata["file"] = str(path)
            write_metadata(path, metadata)
        elif self.auto_prepare.get():
            state, _ = self.prepare_downloaded_copy(path, state, metadata)
        if url:
            self.append_history(platform, url, "browser-download")
        self.emit(f"Browser download pipeline status: {state} ({path.name})")
        return state

    def watch_worker(self):
        seen = {p.resolve() for p in BASE.iterdir() if p.is_file()}
        while not self.stop_watch.wait(2):
            for path in BASE.iterdir():
                if not path.is_file() or path.resolve() in seen or path.suffix.lower() not in VIDEO_EXTS:
                    continue
                size1 = path.stat().st_size
                time.sleep(2)
                if not path.exists() or path.stat().st_size != size1:
                    continue
                selected = self.selected_platforms()
                platform = selected[0] if selected else "Douyin"
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_dir = self.category_download_dir(platform)
                dest = out_dir / f"{platform.lower()}_{stamp}_{safe_name(path.stem)}{path.suffix.lower()}"
                counter = 2
                while dest.exists():
                    dest = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
                    counter += 1
                shutil.move(str(path), str(dest))
                seen.add(dest.resolve())
                self.emit(f"Sorted browser download -> {dest}")
                try:
                    url = self.last_opened_url
                    detected = self.detect_platform(url) if url else None
                    self.process_browser_download(dest, detected or platform, url)
                except Exception as exc:
                    self.emit(f"Browser download inspection failed: {exc}")


if __name__ == "__main__":
    ensure_dirs()
    root = tk.Tk()
    App(root)
    root.mainloop()
