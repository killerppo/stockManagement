from __future__ import annotations

import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from queue import Queue
from zoneinfo import ZoneInfo

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

REPO_ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(REPO_ROOT))

from stock_management.data.calendar import TZ_SHANGHAI  # noqa: E402
from stock_management.data.providers import AkshareKlineProvider, EastmoneyKlineProvider  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402
from stock_management.indicators import IndicatorParams  # noqa: E402
from stock_management.backtest import backtest_breakout_5m, optimize_breakout_5m, summarize_trades  # noqa: E402
from stock_management.signals import breakout_scan_5m  # noqa: E402
from stock_management.signals.params import BreakoutParams  # noqa: E402
from stock_management.storage import SQLiteSignalStore  # noqa: E402
from stock_management.watchlist import (  # noqa: E402
    WatchItem,
    filter_watchlist,
    load_watchlist,
    save_watchlist,
    validate_watchlist,
)


def _normalize_tz_suffix(s: str) -> str:
    s = s.strip()
    if s.endswith("+08"):
        return s[:-3] + "+08:00"
    if s.endswith("-08"):
        return s[:-3] + "-08:00"
    if len(s) >= 5 and (s[-5] in ("+", "-")) and s[-2:] == "00" and s[-3] != ":":
        # e.g. +0800 -> +08:00
        return s[:-2] + ":" + s[-2:]
    return s


def _parse_dt(value: str) -> datetime:
    raw = _normalize_tz_suffix(value)
    raw = raw.strip()
    if not raw:
        raise ValueError("empty datetime")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # fallback for common formats
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                dt = None  # type: ignore[assignment]
        if dt is None:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt.astimezone(TZ_SHANGHAI)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(TZ_SHANGHAI).replace(second=0, microsecond=0)
    return dt.isoformat()


def _now_minute() -> datetime:
    return datetime.now(tz=TZ_SHANGHAI).replace(second=0, microsecond=0)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("stockManagement")
        self.geometry("1200x780")
        self.minsize(1000, 650)
        self._init_style()

        self._log_queue: Queue[str] = Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._status_var = tk.StringVar(value="Ready")

        self.repo_root = REPO_ROOT
        self.watchlist_path = self.repo_root / "config" / "watchlist.csv"
        self.data_dir = self.repo_root / "data"
        self.signals_db = self.data_dir / "signals.sqlite"

        self.var_provider = tk.StringVar(value="akshare")
        provider = self._build_provider(self.var_provider.get())
        self.data_service = DataService.with_default_store(provider=provider, data_dir=self.data_dir)
        self.signal_store = SQLiteSignalStore(self.signals_db)

        self._signals_cache: dict[int, object] = {}
        self.var_sig_page_size = tk.StringVar(value="50")
        self.var_sig_scope = tk.StringVar(value="watchlist")
        self._sig_offset = 0
        self._sig_total = 0
        self._sig_page_var = tk.StringVar(value="")
        self._sig_prev_btn: ttk.Button | None = None
        self._sig_next_btn: ttk.Button | None = None
        self._watch_items: list[WatchItem] = []
        self._backtest_window: BacktestWindow | None = None
        self._build_ui()
        self.after(100, self._drain_logs)
        self._load_watchlist()
        self._reload_signals()

    # ---------- UI ----------
    def _init_style(self) -> None:
        style = ttk.Style(self)
        themes = set(style.theme_names())
        for name in ("vista", "clam", "default"):
            if name in themes:
                try:
                    style.theme_use(name)
                except Exception:
                    pass
                break

        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=24)
        style.configure("Treeview.Heading", padding=(6, 6))
        try:
            style.map(
                "Treeview",
                background=[("selected", "#cce8ff")],
                foreground=[("selected", "black")],
            )
        except Exception:
            pass

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(12, 10))
        root.pack(fill="both", expand=True)

        # ---- Controls (compact) ----
        ctrl = ttk.Frame(root)
        ctrl.pack(fill="x")

        self.var_group = tk.StringVar(value="")
        self.var_limit = tk.StringVar(value="0")
        self.var_window = tk.StringVar(value="60")
        self.var_signal_window = tk.StringVar(value="240")
        self.var_interval = tk.StringVar(value="60")
        self.var_auto_scan = tk.BooleanVar(value=False)
        self.var_lookback = tk.StringVar(value="20")
        self.var_vol_factor = tk.StringVar(value="1.5")
        self.var_start = tk.StringVar(value="")
        self.var_end = tk.StringVar(value="")
        self.var_use_fixed = tk.BooleanVar(value=False)
        self.var_log_signals = tk.BooleanVar(value=True)

        ttk.Label(ctrl, text="Provider").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            ctrl,
            textvariable=self.var_provider,
            values=["akshare", "eastmoney"],
            width=10,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=(6, 14))

        ttk.Label(ctrl, text="Group").grid(row=0, column=2, sticky="w")
        ttk.Entry(ctrl, textvariable=self.var_group, width=12).grid(row=0, column=3, sticky="w", padx=(6, 14))

        ttk.Label(ctrl, text="Limit").grid(row=0, column=4, sticky="w")
        ttk.Entry(ctrl, textvariable=self.var_limit, width=6).grid(row=0, column=5, sticky="w", padx=(6, 14))

        ttk.Label(ctrl, text="Window(min)").grid(row=0, column=6, sticky="w")
        ttk.Entry(ctrl, textvariable=self.var_window, width=8).grid(row=0, column=7, sticky="w", padx=(6, 14))

        ttk.Label(ctrl, text="SignalWindow(min)").grid(row=0, column=8, sticky="w")
        ttk.Entry(ctrl, textvariable=self.var_signal_window, width=10).grid(row=0, column=9, sticky="w", padx=(6, 14))

        self._adv_open = False
        self._adv_btn = ttk.Button(ctrl, text="Advanced ▾", command=self._toggle_advanced)
        self._adv_btn.grid(row=0, column=10, sticky="e")
        ctrl.columnconfigure(10, weight=1)

        ttk.Separator(root).pack(fill="x", pady=(10, 8))

        # ---- Time range ----
        timebar = ttk.Frame(root)
        timebar.pack(fill="x")

        ttk.Checkbutton(timebar, text="Use Start/End", variable=self.var_use_fixed, command=self._on_toggle_fixed).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(timebar, text="Start").grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.start_entry = ttk.Entry(timebar, textvariable=self.var_start, width=28, state="disabled")
        self.start_entry.grid(row=0, column=2, sticky="we", padx=(6, 6))
        ttk.Button(timebar, text="Pick", command=lambda: self._pick_datetime(self.var_start, title="Pick Start")).grid(
            row=0, column=3, sticky="w"
        )

        ttk.Label(timebar, text="End").grid(row=0, column=4, sticky="w", padx=(14, 0))
        self.end_entry = ttk.Entry(timebar, textvariable=self.var_end, width=28, state="disabled")
        self.end_entry.grid(row=0, column=5, sticky="we", padx=(6, 6))
        ttk.Button(timebar, text="Pick", command=lambda: self._pick_datetime(self.var_end, title="Pick End")).grid(
            row=0, column=6, sticky="w"
        )
        ttk.Button(timebar, text="Today 09:30-15:00", command=self._fill_today_session).grid(
            row=0, column=7, sticky="e", padx=(14, 0)
        )
        timebar.columnconfigure(2, weight=1)
        timebar.columnconfigure(5, weight=1)

        # ---- Advanced (collapsible) ----
        self._adv_frame = ttk.LabelFrame(root, text="Advanced")
        # initially hidden

        ttk.Label(self._adv_frame, text="Interval(s)").grid(row=0, column=0, sticky="w", padx=(10, 0), pady=8)
        ttk.Entry(self._adv_frame, textvariable=self.var_interval, width=10).grid(row=0, column=1, sticky="w", padx=6, pady=8)
        ttk.Checkbutton(
            self._adv_frame, text="Auto scan in loop", variable=self.var_auto_scan, command=self._on_toggle_auto_scan
        ).grid(row=0, column=2, sticky="w", padx=(14, 0), pady=8)
        ttk.Checkbutton(
            self._adv_frame, text="Log signals to SQLite", variable=self.var_log_signals, command=self._on_toggle_log_signals
        ).grid(row=0, column=3, sticky="w", padx=(14, 0), pady=8)

        ttk.Label(self._adv_frame, text="Lookback").grid(row=1, column=0, sticky="w", padx=(10, 0), pady=(0, 10))
        ttk.Entry(self._adv_frame, textvariable=self.var_lookback, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=(0, 10))
        ttk.Label(self._adv_frame, text="VolFactor").grid(row=1, column=2, sticky="w", padx=(14, 0), pady=(0, 10))
        ttk.Entry(self._adv_frame, textvariable=self.var_vol_factor, width=10).grid(row=1, column=3, sticky="w", padx=6, pady=(0, 10))

        ttk.Button(self._adv_frame, text="Start Loop", command=self._on_start_loop).grid(
            row=0, column=4, rowspan=2, sticky="ns", padx=(18, 6), pady=8
        )
        ttk.Button(self._adv_frame, text="Stop", command=self._on_stop).grid(
            row=0, column=5, rowspan=2, sticky="ns", padx=(0, 10), pady=8
        )

        # ---- Tabs ----
        notebook = ttk.Notebook(root)
        self._notebook = notebook
        notebook.pack(fill="both", expand=True, pady=(10, 0))

        tab_watch = ttk.Frame(notebook, padding=(8, 8))
        tab_signals = ttk.Frame(notebook, padding=(8, 8))
        tab_log = ttk.Frame(notebook, padding=(8, 8))
        notebook.add(tab_watch, text="Watchlist")
        notebook.add(tab_signals, text="Signals")
        notebook.add(tab_log, text="Log")

        # Watchlist tab
        w_hdr = ttk.Frame(tab_watch)
        w_hdr.pack(fill="x")
        ttk.Button(w_hdr, text="Reload", command=self._load_watchlist).pack(side="left")
        ttk.Button(w_hdr, text="Add", command=self._on_add_symbol).pack(side="left", padx=(6, 0))
        ttk.Button(w_hdr, text="Edit", command=self._on_edit_symbol).pack(side="left", padx=(6, 0))
        ttk.Button(w_hdr, text="Delete", command=self._on_delete_symbol).pack(side="left", padx=(6, 0))
        ttk.Button(w_hdr, text="Save", command=self._on_save_watchlist).pack(side="left", padx=(6, 0))
        ttk.Separator(w_hdr, orient="vertical").pack(side="left", fill="y", padx=10, pady=2)
        ttk.Button(w_hdr, text="Refresh Cache", command=self._on_refresh).pack(side="left")
        ttk.Button(w_hdr, text="Show Kline", command=self._on_show_kline).pack(side="left", padx=(6, 0))
        ttk.Button(w_hdr, text="Backtest", command=self._on_open_backtest).pack(side="left", padx=(6, 0))

        w_body = ttk.Frame(tab_watch)
        w_body.pack(fill="both", expand=True, pady=(10, 0))
        self.watch_tree = ttk.Treeview(
            w_body,
            columns=("symbol", "group", "enabled", "note", "last_ts", "last_close", "changes"),
            show="headings",
            selectmode="browse",
        )
        for col, w in [
            ("symbol", 95),
            ("group", 85),
            ("enabled", 70),
            ("note", 220),
            ("last_ts", 160),
            ("last_close", 95),
            ("changes", 80),
        ]:
            self.watch_tree.heading(col, text=col)
            self.watch_tree.column(col, width=w, anchor="w", stretch=(col in ("note", "last_ts")))
        self.watch_tree.tag_configure("odd", background="#f7f7f7")
        self.watch_tree.bind("<Double-1>", lambda _e: self._on_show_kline())
        w_scroll = ttk.Scrollbar(w_body, orient="vertical", command=self.watch_tree.yview)
        self.watch_tree.configure(yscrollcommand=w_scroll.set)
        self.watch_tree.pack(side="left", fill="both", expand=True)
        w_scroll.pack(side="right", fill="y")

        # Signals tab
        s_hdr = ttk.Frame(tab_signals)
        s_hdr.pack(fill="x")
        ttk.Button(s_hdr, text="Scan Signals", command=self._on_scan).pack(side="left")
        ttk.Button(s_hdr, text="Refresh+Scan", command=self._on_refresh_scan).pack(side="left", padx=(6, 0))
        ttk.Button(s_hdr, text="Reload", command=lambda: self._reload_signals()).pack(side="left", padx=(6, 0))

        ttk.Label(s_hdr, text="Scope").pack(side="left", padx=(14, 0))
        sig_scope_combo = ttk.Combobox(
            s_hdr,
            textvariable=self.var_sig_scope,
            values=["watchlist", "all"],
            width=10,
            state="readonly",
        )
        sig_scope_combo.pack(side="left", padx=(6, 0))
        sig_scope_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_signals_scope())

        ttk.Label(s_hdr, textvariable=self._sig_page_var).pack(side="right", padx=(0, 8))
        self._sig_next_btn = ttk.Button(s_hdr, text="Next", command=self._on_signals_next)
        self._sig_next_btn.pack(side="right", padx=(4, 0))
        self._sig_prev_btn = ttk.Button(s_hdr, text="Prev", command=self._on_signals_prev)
        self._sig_prev_btn.pack(side="right")
        ttk.Label(s_hdr, text="PerPage").pack(side="right")
        sig_page_combo = ttk.Combobox(
            s_hdr,
            textvariable=self.var_sig_page_size,
            values=["25", "50", "100", "200"],
            width=5,
            state="readonly",
        )
        sig_page_combo.pack(side="right", padx=(4, 10))
        sig_page_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_signals_page_size())

        s_pane = ttk.PanedWindow(tab_signals, orient="vertical")
        s_pane.pack(fill="both", expand=True, pady=(10, 0))

        s_top = ttk.Frame(s_pane)
        s_bot = ttk.Frame(s_pane)
        s_pane.add(s_top, weight=3)
        s_pane.add(s_bot, weight=2)

        self.sig_tree = ttk.Treeview(
            s_top,
            columns=("ts", "symbol", "strategy", "dir", "score", "entry", "stop", "tp1", "tp2"),
            show="headings",
            selectmode="browse",
        )
        for col, w in [
            ("ts", 170),
            ("symbol", 90),
            ("strategy", 120),
            ("dir", 70),
            ("score", 60),
            ("entry", 130),
            ("stop", 90),
            ("tp1", 90),
            ("tp2", 90),
        ]:
            self.sig_tree.heading(col, text=col)
            self.sig_tree.column(col, width=w, anchor="w", stretch=(col == "entry"))
        self.sig_tree.tag_configure("odd", background="#f7f7f7")
        self.sig_tree.bind("<<TreeviewSelect>>", self._on_signal_select)
        s_scroll = ttk.Scrollbar(s_top, orient="vertical", command=self.sig_tree.yview)
        self.sig_tree.configure(yscrollcommand=s_scroll.set)
        self.sig_tree.pack(side="left", fill="both", expand=True)
        s_scroll.pack(side="right", fill="y")

        ttk.Label(s_bot, text="Signal Details").pack(anchor="w")
        details_wrap = ttk.Frame(s_bot)
        details_wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.sig_details = tk.Text(details_wrap, height=10, wrap="none")
        d_scroll = ttk.Scrollbar(details_wrap, orient="vertical", command=self.sig_details.yview)
        self.sig_details.configure(yscrollcommand=d_scroll.set)
        self.sig_details.pack(side="left", fill="both", expand=True)
        d_scroll.pack(side="right", fill="y")

        # Log tab
        log_hdr = ttk.Frame(tab_log)
        log_hdr.pack(fill="x")
        ttk.Button(log_hdr, text="Clear", command=lambda: self.log_text.delete("1.0", "end")).pack(side="left")

        log_wrap = ttk.Frame(tab_log)
        log_wrap.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_wrap, height=10, wrap="none")
        l_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=l_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        l_scroll.pack(side="right", fill="y")

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(10, 0))
        ttk.Label(status, textvariable=self._status_var).pack(anchor="w")

    def _toggle_advanced(self) -> None:
        self._adv_open = not bool(getattr(self, "_adv_open", False))
        if self._adv_open:
            try:
                self._adv_btn.configure(text="Advanced ▴")
            except Exception:
                pass
            # Keep Advanced between timebar and tabs.
            try:
                self._adv_frame.pack(fill="x", pady=(10, 0), before=self._notebook)
            except Exception:
                self._adv_frame.pack(fill="x", pady=(10, 0))
        else:
            try:
                self._adv_btn.configure(text="Advanced ▾")
            except Exception:
                pass
            self._adv_frame.pack_forget()

    def _build_provider(self, name: str):
        name = (name or "").strip().lower()
        if name == "akshare":
            return AkshareKlineProvider()
        return EastmoneyKlineProvider()

    def _ensure_provider(self) -> None:
        # Rebuild service so all downstream (kline/backtest/scan) shares the same provider.
        name = (self.var_provider.get() or "").strip().lower()
        cur = getattr(self, "_provider_name", None)
        if cur == name and getattr(self, "data_service", None) is not None:
            return
        self._provider_name = name
        self._log(f"provider set to {name}")
        self.data_service = DataService.with_default_store(provider=self._build_provider(name), data_dir=self.data_dir)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _notify_error(self, title: str, msg: str) -> None:
        self._log(f"ERROR {title}: {msg}")
        try:
            messagebox.showerror(title, msg)
        except Exception:
            # In case messagebox fails (rare), at least keep logs.
            pass

    def _on_toggle_fixed(self) -> None:
        enabled = bool(self.var_use_fixed.get())
        self._log(f"toggle: Use Start/End -> {enabled}")
        state = "normal" if enabled else "disabled"
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)
        if not enabled:
            self.var_start.set("")
            self.var_end.set("")

    def _on_toggle_log_signals(self) -> None:
        self._log(f"toggle: Log signals -> {bool(self.var_log_signals.get())}")

    def _on_toggle_auto_scan(self) -> None:
        self._log(f"toggle: Auto scan -> {bool(self.var_auto_scan.get())}")

    def _fill_today_session(self) -> None:
        now = _now_minute()
        day = now.date()
        start = datetime.combine(day, datetime.strptime("09:30", "%H:%M").time(), TZ_SHANGHAI)
        end = datetime.combine(day, datetime.strptime("15:00", "%H:%M").time(), TZ_SHANGHAI)
        self.var_use_fixed.set(True)
        self._on_toggle_fixed()
        self.var_start.set(_fmt_dt(start))
        self.var_end.set(_fmt_dt(end))
        self._log(f"fill today session start={self.var_start.get()} end={self.var_end.get()}")

    def _pick_datetime(self, target_var: tk.StringVar, *, title: str) -> None:
        self._log(f"pick datetime opened title={title}")
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.geometry("360x170")
        dlg.transient(self)
        dlg.grab_set()

        now = _now_minute()
        date_var = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        hour_var = tk.StringVar(value=now.strftime("%H"))
        min_var = tk.StringVar(value=now.strftime("%M"))

        frm = ttk.Frame(dlg)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frm, text="Date (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=date_var, width=14).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(frm, text="Hour").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(frm, from_=0, to=23, textvariable=hour_var, width=6).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(frm, text="Minute").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(frm, from_=0, to=59, textvariable=min_var, width=6).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        quick = ttk.Frame(frm)
        quick.grid(row=0, column=2, rowspan=3, padx=(12, 0), sticky="ns")
        ttk.Button(quick, text="Now", command=lambda: (hour_var.set(now.strftime("%H")), min_var.set(now.strftime("%M")))).pack(fill="x", pady=2)
        ttk.Button(quick, text="09:30", command=lambda: (hour_var.set("09"), min_var.set("30"))).pack(fill="x", pady=2)
        ttk.Button(quick, text="15:00", command=lambda: (hour_var.set("15"), min_var.set("00"))).pack(fill="x", pady=2)

        def ok() -> None:
            try:
                d = datetime.strptime(date_var.get().strip(), "%Y-%m-%d").date()
                h = int(hour_var.get())
                m = int(min_var.get())
                dt = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ_SHANGHAI)
            except Exception as e:
                self._log(f"ERROR pick datetime: {e}")
                return
            target_var.set(_fmt_dt(dt))
            self.var_use_fixed.set(True)
            self._on_toggle_fixed()
            self._log(f"pick datetime ok title={title} value={target_var.get()}")
            dlg.destroy()

        ttk.Button(frm, text="OK", command=ok).grid(row=3, column=0, pady=(10, 0), sticky="w")
        ttk.Button(frm, text="Cancel", command=dlg.destroy).grid(row=3, column=1, pady=(10, 0), sticky="w", padx=6)

    # ---------- Helpers ----------
    def _log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _drain_logs(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
        except Exception:
            pass
        self.after(100, self._drain_logs)

    def _get_symbols(self) -> list[tuple[str, str | None, bool, str | None]]:
        raise RuntimeError("_get_symbols should not be called from worker threads; use _snapshot_symbols instead")

    def _get_window(self) -> tuple[datetime, datetime]:
        raise RuntimeError("_get_window should not be called from worker threads; use _snapshot_window/_window_now instead")

    def _snapshot_symbols(self) -> list[tuple[str, str | None, bool, str | None]]:
        items = load_watchlist(self.watchlist_path)
        issues = validate_watchlist(items)
        if issues:
            raise RuntimeError(f"watchlist invalid: {issues[0].message}")

        group = self.var_group.get().strip() or None
        items = filter_watchlist(items, group=group, enabled_only=True)

        limit = int(self.var_limit.get() or "0")
        if limit > 0:
            items = items[:limit]
        return [(i.symbol, i.group, i.enabled, i.note) for i in items]

    def _snapshot_window(self) -> tuple[datetime, datetime] | None:
        if not bool(self.var_use_fixed.get()):
            return None
        s = self.var_start.get().strip()
        e = self.var_end.get().strip()
        if not (s and e):
            raise RuntimeError("Use Start/End is enabled: Start and End must both be set")
        return _parse_dt(s), _parse_dt(e)

    def _window_now(self, window_minutes: int) -> tuple[datetime, datetime]:
        end = _now_minute()
        start = end - timedelta(minutes=max(window_minutes, 1))
        return start, end

    def _snapshot_int(self, var: tk.StringVar, default: int) -> int:
        raw = (var.get() or "").strip()
        if raw == "":
            return default
        return int(raw)

    # ---------- Actions ----------
    def _load_watchlist(self) -> None:
        self._log("clicked: Reload Watchlist")
        self.watch_tree.delete(*self.watch_tree.get_children())
        try:
            items = load_watchlist(self.watchlist_path)
            issues = validate_watchlist(items)
            if issues:
                raise RuntimeError(issues[0].message)
            self._watch_items = items
            symbols = self._snapshot_symbols()
        except Exception as e:
            self._log(f"ERROR load watchlist: {e}")
            return
        for idx, (sym, group, enabled, note) in enumerate(symbols, start=1):
            self.watch_tree.insert(
                "",
                "end",
                iid=sym,
                values=(sym, group or "", "1" if enabled else "0", note or "", "", "", ""),
                tags=("odd",) if (idx % 2 == 1) else (),
            )
        self._log(f"watchlist loaded: {len(symbols)} symbols")
        if (self.var_sig_scope.get() or "watchlist").strip().lower() != "all":
            self._sig_offset = 0
            self._reload_signals(reason="Watchlist Changed")

    def _selected_symbol(self) -> str | None:
        sel = self.watch_tree.selection()
        if not sel:
            return None
        return str(sel[0])

    def _prompt_watch_item(self, title: str, initial: WatchItem | None = None) -> WatchItem | None:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.geometry("420x220")
        dlg.transient(self)
        dlg.grab_set()

        sym_var = tk.StringVar(value=(initial.symbol if initial else ""))
        group_var = tk.StringVar(value=(initial.group or "" if initial else ""))
        enabled_var = tk.BooleanVar(value=(initial.enabled if initial else True))
        note_var = tk.StringVar(value=(initial.note or "" if initial else ""))

        frm = ttk.Frame(dlg)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frm, text="Symbol (000001.SZ)").grid(row=0, column=0, sticky="w")
        e_sym = ttk.Entry(frm, textvariable=sym_var, width=20)
        e_sym.grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(frm, text="Group").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frm, textvariable=group_var, width=20).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Checkbutton(frm, text="Enabled", variable=enabled_var).grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Label(frm, text="Note").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        ttk.Entry(frm, textvariable=note_var, width=36).grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))

        result: WatchItem | None = None

        def ok() -> None:
            nonlocal result
            symbol = sym_var.get().strip().upper()
            if not symbol:
                self._notify_error(title, "Symbol is required")
                return
            result = WatchItem(
                symbol=symbol,
                group=(group_var.get().strip() or None),
                enabled=bool(enabled_var.get()),
                note=(note_var.get().strip() or None),
            )
            dlg.destroy()

        ttk.Button(frm, text="OK", command=ok).grid(row=4, column=0, pady=(14, 0), sticky="w")
        ttk.Button(frm, text="Cancel", command=dlg.destroy).grid(row=4, column=1, pady=(14, 0), sticky="w", padx=6)

        if not initial:
            e_sym.focus_set()

        self.wait_window(dlg)
        return result

    def _on_add_symbol(self) -> None:
        self._log("clicked: Add Symbol")
        item = self._prompt_watch_item("Add Symbol")
        if item is None:
            self._log("add symbol cancelled")
            return
        items = load_watchlist(self.watchlist_path)
        items.append(item)
        issues = validate_watchlist(items)
        if issues:
            self._notify_error("Add Symbol", issues[0].message)
            return
        self._watch_items = items
        save_watchlist(self._watch_items, self.watchlist_path)
        self._load_watchlist()

    def _on_edit_symbol(self) -> None:
        self._log("clicked: Edit Selected")
        sym = self._selected_symbol()
        if not sym:
            self._notify_error("Edit Selected", "Select a symbol first")
            return
        items = load_watchlist(self.watchlist_path)
        current = next((i for i in items if i.symbol.upper() == sym.upper()), None)
        if current is None:
            self._notify_error("Edit Selected", f"Symbol not found: {sym}")
            return
        updated = self._prompt_watch_item("Edit Symbol", initial=current)
        if updated is None:
            self._log("edit symbol cancelled")
            return
        new_items: list[WatchItem] = []
        for it in items:
            if it.symbol.upper() == current.symbol.upper():
                new_items.append(updated)
            else:
                new_items.append(it)
        issues = validate_watchlist(new_items)
        if issues:
            self._notify_error("Edit Selected", issues[0].message)
            return
        self._watch_items = new_items
        save_watchlist(self._watch_items, self.watchlist_path)
        self._load_watchlist()

    def _on_delete_symbol(self) -> None:
        self._log("clicked: Delete Selected")
        sym = self._selected_symbol()
        if not sym:
            self._notify_error("Delete Selected", "Select a symbol first")
            return
        if not messagebox.askyesno("Delete Selected", f"Delete {sym} from watchlist?"):
            self._log("delete symbol cancelled")
            return
        items = [i for i in load_watchlist(self.watchlist_path) if i.symbol.upper() != sym.upper()]
        self._watch_items = items
        save_watchlist(self._watch_items, self.watchlist_path)
        self._load_watchlist()

    def _on_save_watchlist(self) -> None:
        self._log("clicked: Save Watchlist")
        items = load_watchlist(self.watchlist_path)
        issues = validate_watchlist(items)
        if issues:
            self._notify_error("Save Watchlist", issues[0].message)
            return
        self._watch_items = items
        save_watchlist(self._watch_items, self.watchlist_path)
        self._log("watchlist saved")

    def _on_show_kline(self) -> None:
        self._log("clicked: Show Kline")
        sym = self._selected_symbol()
        if not sym:
            self._notify_error("Show Kline", "Select a symbol first")
            return
        self._ensure_provider()
        self._log(f"show kline symbol={sym}")
        KlineWindow(self, symbol=sym, data_service=self.data_service)

    def _on_open_backtest(self) -> None:
        self._log("clicked: Backtest")
        if self._backtest_window and self._backtest_window.winfo_exists():
            self._backtest_window.focus()
            return
        self._backtest_window = BacktestWindow(self)

    def _snapshot_sig_page_size(self) -> int:
        try:
            n = int((self.var_sig_page_size.get() or "").strip() or "50")
        except Exception:
            n = 50
        return max(1, min(500, n))

    def _on_signals_page_size(self) -> None:
        self._sig_offset = 0
        self._log(f"signals page_size -> {self._snapshot_sig_page_size()}")
        self._reload_signals(reason="Signals PageSize")

    def _on_signals_scope(self) -> None:
        self._sig_offset = 0
        self._log(f"signals scope -> {self.var_sig_scope.get()}")
        self._reload_signals(reason="Signals Scope")

    def _on_signals_prev(self) -> None:
        page_size = self._snapshot_sig_page_size()
        self._sig_offset = max(0, self._sig_offset - page_size)
        self._log(f"clicked: Signals Prev offset={self._sig_offset} page_size={page_size}")
        self._reload_signals(reason="Signals Prev")

    def _on_signals_next(self) -> None:
        page_size = self._snapshot_sig_page_size()
        if self._sig_offset + page_size < self._sig_total:
            self._sig_offset += page_size
        self._log(f"clicked: Signals Next offset={self._sig_offset} page_size={page_size}")
        self._reload_signals(reason="Signals Next")

    def _reload_signals(self, *, reason: str = "Reload Signals") -> None:
        self._log(f"clicked: {reason}")
        self.sig_tree.delete(*self.sig_tree.get_children())
        self._signals_cache.clear()
        try:
            page_size = self._snapshot_sig_page_size()
            scope = (self.var_sig_scope.get() or "watchlist").strip().lower()
            symbols: list[str] | None
            if scope == "all":
                symbols = None
            else:
                try:
                    symbols = [s for s, _g, _e, _n in self._snapshot_symbols()]
                except Exception as e:
                    self._log(f"WARN signals scope=watchlist but watchlist invalid: {e}")
                    symbols = None

            total = self.signal_store.count_signals(symbols=symbols)
            self._sig_total = total
            if total <= 0:
                self._sig_offset = 0
            else:
                last_offset = ((total - 1) // page_size) * page_size
                if self._sig_offset > last_offset:
                    self._sig_offset = last_offset
            rows = self.signal_store.list_recent(limit=page_size, offset=self._sig_offset, symbols=symbols)
        except Exception as e:
            self._log(f"ERROR load signals: {e}")
            return

        for idx, r in enumerate(rows, start=1):
            self._signals_cache[r.id] = r
            entry = f"[{r.entry_low:.3f},{r.entry_high:.3f}]"
            self.sig_tree.insert(
                "",
                "end",
                iid=str(r.id),
                values=(
                    r.ts.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M"),
                    r.symbol,
                    r.strategy_id,
                    r.direction,
                    r.score,
                    entry,
                    f"{r.stop_loss:.3f}",
                    f"{r.tp1:.3f}",
                    f"{r.tp2:.3f}",
                ),
                tags=("odd",) if (idx % 2 == 1) else (),
            )
        page_size = self._snapshot_sig_page_size()
        if self._sig_total <= 0:
            self._sig_page_var.set("0/0 total=0")
        else:
            page_count = (self._sig_total + page_size - 1) // page_size
            page_index = (self._sig_offset // page_size) + 1
            self._sig_page_var.set(f"{page_index}/{page_count} total={self._sig_total}")
        if self._sig_prev_btn is not None:
            self._sig_prev_btn["state"] = "disabled" if self._sig_offset <= 0 else "normal"
        if self._sig_next_btn is not None:
            self._sig_next_btn["state"] = "disabled" if (self._sig_offset + page_size) >= self._sig_total else "normal"
        self._log(f"signals loaded: {len(rows)}")

    def _on_signal_select(self, _evt=None) -> None:
        sel = self.sig_tree.selection()
        if not sel:
            return
        try:
            rid = int(sel[0])
        except Exception:
            return
        row = self._signals_cache.get(rid)
        if row is None:
            return
        self._log(f"select signal id={rid} symbol={row.symbol}")
        # Render a readable detail view (JSON-ish).
        detail_lines = [
            f"id={row.id}",
            f"symbol={row.symbol}",
            f"ts={row.ts.astimezone(TZ_SHANGHAI).isoformat()}",
            f"freq={row.freq}",
            f"strategy={row.strategy_id}",
            f"direction={row.direction} score={row.score}",
            f"entry=[{row.entry_low},{row.entry_high}] stop={row.stop_loss} tp1={row.tp1} tp2={row.tp2}",
            "",
            "reasons:",
        ]
        for r in row.reasons:
            detail_lines.append(f"- {r}")
        detail_lines.append("")
        detail_lines.append("risk_flags:")
        for rf in row.risk_flags:
            detail_lines.append(f"- {rf}")
        detail_lines.append("")
        detail_lines.append("params:")
        detail_lines.append(str(row.params))

        self.sig_details.delete("1.0", "end")
        self.sig_details.insert("end", "\n".join(detail_lines))

    def _on_stop(self) -> None:
        self._stop_event.set()
        self._log("clicked: Stop")

    def _run_in_worker(self, fn) -> None:
        if self._worker and self._worker.is_alive():
            self._log("busy: a task is running")
            self._set_status("Busy")
            return
        self._stop_event.clear()
        self._set_status("Running...")

        def wrapped() -> None:
            try:
                fn()
            finally:
                self.after(0, lambda: self._set_status("Ready"))

        self._worker = threading.Thread(target=wrapped, daemon=True)
        self._worker.start()

    def _on_refresh(self) -> None:
        try:
            self._ensure_provider()
            fixed_window = self._snapshot_window()
            symbols = self._snapshot_symbols()
            window_minutes = self._snapshot_int(self.var_window, 60)
        except Exception as e:
            self._notify_error("Refresh", str(e))
            return

        self._log("clicked: Refresh Cache")
        self._log(
            f"refresh params provider={self.var_provider.get()} fixed={fixed_window is not None} "
            f"window_minutes={window_minutes} symbols={len(symbols)}"
        )

        def task() -> None:
            try:
                if fixed_window is None:
                    start, end = self._window_now(window_minutes)
                else:
                    start, end = fixed_window
                self._log(f"refresh cache start={start.isoformat()} end={end.isoformat()} symbols={len(symbols)}")
                total = 0

                for idx, (sym, group, enabled, _note) in enumerate(symbols, start=1):
                    if self._stop_event.is_set():
                        self._log("refresh stopped")
                        return
                    changed = self.data_service.ensure_1m(sym, start, end)
                    total += changed

                    # load latest close for UI
                    bars = self.data_service.get_bars(sym, "1m", start, end)
                    last_ts = bars[-1].ts.isoformat() if bars else ""
                    last_close = f"{bars[-1].close:.3f}" if bars else ""
                    if fixed_window is not None or not bars:
                        first_ts = bars[0].ts.isoformat() if bars else ""
                        self._log(
                            f"[{idx}/{len(symbols)}] {sym} bars_1m={len(bars)} first={first_ts} last={last_ts}"
                        )

                    def update_row(symbol=sym, ch=changed, ts=last_ts, close=last_close) -> None:
                        if not self.watch_tree.exists(symbol):
                            return
                        vals = list(self.watch_tree.item(symbol, "values"))
                        # columns: symbol, group, enabled, note, last_ts, last_close, changes
                        vals[4] = ts
                        vals[5] = close
                        vals[6] = str(ch)
                        self.watch_tree.item(symbol, values=vals)

                    self.after(0, update_row)
                    self._log(f"[{idx}/{len(symbols)}] {sym} upserted_changes={changed}")

                self._log(f"refresh done total_upserted_changes={total}")
            except Exception as e:
                self._log(f"ERROR refresh: {e}")
                self._log(traceback.format_exc())

        self._run_in_worker(task)

    def _on_refresh_scan(self) -> None:
        try:
            self._ensure_provider()
            fixed_window = self._snapshot_window()
            symbols = self._snapshot_symbols()
            window_minutes = self._snapshot_int(self.var_window, 60)
            signal_window = self._snapshot_int(self.var_signal_window, 240)
            log_signals = bool(self.var_log_signals.get())
            lookback = self._snapshot_int(self.var_lookback, 20)
            vol_factor = float((self.var_vol_factor.get() or "1.5").strip())
        except Exception as e:
            self._notify_error("Refresh+Scan", str(e))
            return

        self._log("clicked: Refresh+Scan")
        self._log(
            f"refresh+scan params provider={self.var_provider.get()} fixed={fixed_window is not None} window_minutes={window_minutes} "
            f"signal_window={signal_window} lookback={lookback} vol_factor={vol_factor} "
            f"log_signals={log_signals} symbols={len(symbols)}"
        )
        scan_start = fixed_window[0] if fixed_window is not None else None

        def task() -> None:
            try:
                if fixed_window is None:
                    start, end = self._window_now(window_minutes)
                else:
                    start, end = fixed_window
                self._log(f"refresh+scan start={start.isoformat()} end={end.isoformat()} symbols={len(symbols)}")

                total = 0
                for idx, (sym, _group, _enabled, _note) in enumerate(symbols, start=1):
                    if self._stop_event.is_set():
                        self._log("refresh stopped")
                        return
                    changed = self.data_service.ensure_1m(sym, start, end)
                    total += changed
                    self._log(f"[{idx}/{len(symbols)}] {sym} upserted_changes={changed}")

                self._log(f"refresh done total_upserted_changes={total}")
            except Exception as e:
                self._log(f"ERROR refresh: {e}")
                self._log(traceback.format_exc())
                return

            # then scan
            self._scan_task(
                symbols=symbols,
                end=end,
                signal_window_minutes=signal_window,
                log_signals=log_signals,
                lookback=lookback,
                vol_factor=vol_factor,
                start=scan_start,
            )

        self._run_in_worker(task)

    def _on_scan(self) -> None:
        try:
            self._ensure_provider()
            fixed_window = self._snapshot_window()
            symbols = self._snapshot_symbols()
            window_minutes = self._snapshot_int(self.var_window, 60)
            signal_window = self._snapshot_int(self.var_signal_window, 240)
            log_signals = bool(self.var_log_signals.get())
        except Exception as e:
            self._notify_error("Scan Signals", str(e))
            return

        self._log("clicked: Scan Signals")

        end = (fixed_window[1] if fixed_window else self._window_now(window_minutes)[1])
        scan_start = fixed_window[0] if fixed_window is not None else None
        lookback = self._snapshot_int(self.var_lookback, 20)
        vol_factor = float((self.var_vol_factor.get() or "1.5").strip())
        self._log(
            f"scan params provider={self.var_provider.get()} fixed={fixed_window is not None} window_minutes={window_minutes} "
            f"signal_window={signal_window} lookback={lookback} vol_factor={vol_factor} "
            f"log_signals={log_signals} symbols={len(symbols)}"
        )
        self._run_in_worker(
            lambda: self._scan_task(
                symbols=symbols,
                end=end,
                signal_window_minutes=signal_window,
                log_signals=log_signals,
                lookback=lookback,
                vol_factor=vol_factor,
                start=scan_start,
            )
        )

    def _scan_task(
        self,
        *,
        symbols: list[tuple[str, str | None, bool, str | None]],
        end: datetime,
        signal_window_minutes: int,
        log_signals: bool,
        lookback: int = 20,
        vol_factor: float = 1.5,
        start: datetime | None = None,
    ) -> None:
        try:
            if start is None:
                sig_start = end - timedelta(minutes=max(signal_window_minutes, 1))
            else:
                sig_start = start
            self._log(f"scan signals sig_start={sig_start.isoformat()} end={end.isoformat()} symbols={len(symbols)}")

            ind_params = IndicatorParams()
            strat_params = BreakoutParams(lookback=lookback, vol_factor=vol_factor)
            params_snapshot = {"indicator_params": asdict(ind_params), "strategy_params": asdict(strat_params)}

            emitted = 0
            stored = 0
            for idx, (sym, _group, _enabled, _note) in enumerate(symbols, start=1):
                if self._stop_event.is_set():
                    self._log("scan stopped")
                    return
                bars_5m = self.data_service.get_bars(sym, "5m", sig_start, end)
                if bars_5m:
                    self._log(
                        f"[{idx}/{len(symbols)}] {sym} bars_5m={len(bars_5m)} "
                        f"first={bars_5m[0].ts.isoformat()} last={bars_5m[-1].ts.isoformat()}"
                    )
                else:
                    self._log(f"[{idx}/{len(symbols)}] {sym} bars_5m=0")
                required = max(strat_params.lookback + 1, strat_params.swing_lookback + 1)
                if len(bars_5m) < required:
                    self._log(
                        f"[{idx}/{len(symbols)}] {sym} skip: bars_5m<{required} "
                        f"(lookback={strat_params.lookback} swing_lb={strat_params.swing_lookback})"
                    )
                    continue
                sigs = breakout_scan_5m(symbol=sym, bars_5m=bars_5m, ind_params=ind_params, params=strat_params)
                emitted += len(sigs)

                if log_signals and sigs:
                    added = self.signal_store.insert_signals(
                        sigs, strategy_id="breakout_5m_v1", params_snapshot=params_snapshot
                    )
                    stored += added
                    if added == 0:
                        self._log(f"[{idx}/{len(symbols)}] {sym} signals emitted but stored=0 (likely duplicates)")

                self._log(f"[{idx}/{len(symbols)}] {sym} signals={len(sigs)}")

            self._log(f"scan done emitted={emitted} stored={stored}")
            self.after(0, self._reload_signals)
        except Exception as e:
            self._log(f"ERROR scan: {e}")
            self._log(traceback.format_exc())

    def _on_start_loop(self) -> None:
        try:
            self._ensure_provider()
            fixed_window = self._snapshot_window()
            if fixed_window is not None:
                raise RuntimeError("Loop mode requires Start/End to be empty (rolling window)")
            symbols = self._snapshot_symbols()
            window_minutes = self._snapshot_int(self.var_window, 60)
            signal_window = self._snapshot_int(self.var_signal_window, 240)
            interval = max(1, self._snapshot_int(self.var_interval, 60))
            auto_scan = bool(self.var_auto_scan.get())
            log_signals = bool(self.var_log_signals.get())
        except Exception as e:
            self._notify_error("Start Loop", str(e))
            return

        self._log("clicked: Start Loop")
        self._log(
            f"loop params provider={self.var_provider.get()} window_minutes={window_minutes} signal_window={signal_window} "
            f"interval={interval} auto_scan={auto_scan} log_signals={log_signals} symbols={len(symbols)}"
        )

        def task() -> None:
            try:
                self._log(f"loop started interval_sec={interval} auto_scan={auto_scan}")
                while not self._stop_event.is_set():
                    # refresh
                    start, end = self._window_now(window_minutes)
                    total = 0
                    for idx, (sym, _group, _enabled, _note) in enumerate(symbols, start=1):
                        if self._stop_event.is_set():
                            break
                        changed = self.data_service.ensure_1m(sym, start, end)
                        total += changed
                        self._log(f"[loop refresh {idx}/{len(symbols)}] {sym} upserted_changes={changed}")
                    self._log(f"[loop] refresh done total_upserted_changes={total}")

                    if self._stop_event.is_set():
                        break

                    if auto_scan:
                        self._scan_task(symbols=symbols, end=end, signal_window_minutes=signal_window, log_signals=log_signals)

                    # sleep with early stop
                    for _ in range(interval * 10):
                        if self._stop_event.is_set():
                            break
                        time.sleep(0.1)
                self._log("loop stopped")
            except Exception as e:
                self._log(f"ERROR loop: {e}")
                self._log(traceback.format_exc())

        self._run_in_worker(task)


def main() -> int:
    # Ensure TZ database works under Windows/conda.
    _ = ZoneInfo("Asia/Shanghai")
    app = App()
    app.mainloop()
    return 0


class KlineWindow(tk.Toplevel):
    def __init__(self, parent: App, *, symbol: str, data_service: DataService) -> None:
        super().__init__(parent)
        self.title(f"Kline - {symbol}")
        self.geometry("900x520")
        self.transient(parent)

        self.parent = parent
        self.symbol = symbol
        self.data_service = data_service

        self.var_freq = tk.StringVar(value="5m")
        self.var_bars = tk.StringVar(value="120")
        self.var_scale = tk.StringVar(value="robust")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Symbol").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=self.symbol).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(top, text="Freq").grid(row=0, column=2, sticky="w")
        ttk.Combobox(top, textvariable=self.var_freq, values=["1m", "5m", "15m", "60m"], width=6, state="readonly").grid(
            row=0, column=3, sticky="w", padx=6
        )

        ttk.Label(top, text="Bars").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.var_bars, width=8).grid(row=0, column=5, sticky="w", padx=6)

        ttk.Label(top, text="Scale").grid(row=0, column=6, sticky="w", padx=(12, 0))
        scale_combo = ttk.Combobox(top, textvariable=self.var_scale, values=["robust", "full"], width=8, state="readonly")
        scale_combo.grid(row=0, column=7, sticky="w", padx=6)
        scale_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        ttk.Button(top, text="Refresh", command=self.refresh).grid(row=0, column=8, sticky="w", padx=(12, 0))

        self.canvas = tk.Canvas(self, bg="white")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # refresh after layout so canvas has correct size
        self.after(100, self.refresh)

    def _window_for_chart(self, freq: str, bars: int) -> tuple[datetime, datetime]:
        fixed = self.parent._snapshot_window()
        if fixed is not None:
            return fixed

        end = _now_minute()
        mins = {"1m": 1, "5m": 5, "15m": 15, "60m": 60}[freq]
        start = end - timedelta(minutes=max(1, bars) * mins)
        return start, end

    def refresh(self) -> None:
        try:
            freq = self.var_freq.get()
            bars_n = max(20, int(self.var_bars.get() or "120"))
            scale = (self.var_scale.get() or "robust").strip().lower()
        except Exception as e:
            self.parent._notify_error("Kline", str(e))
            return

        fixed = self.parent._snapshot_window()
        if fixed is not None:
            start, end = fixed
            use_full = True
        else:
            start, end = self._window_for_chart(freq, bars_n)
            use_full = False
        bars = self.data_service.get_bars(self.symbol, freq, start, end)
        if not bars:
            self.canvas.delete("all")
            self.canvas.create_text(20, 20, anchor="nw", text="No bars in range", fill="black")
            return

        if not use_full:
            bars = bars[-bars_n:]
        self._draw_candles(
            bars,
            title=f"{self.symbol} {freq} {bars[0].ts:%Y-%m-%d %H:%M} .. {bars[-1].ts:%H:%M}",
            scale=scale,
        )

    def _quantile(self, xs_sorted: list[float], q: float) -> float:
        if not xs_sorted:
            return 0.0
        q = max(0.0, min(1.0, float(q)))
        if len(xs_sorted) == 1:
            return float(xs_sorted[0])
        pos = q * (len(xs_sorted) - 1)
        lo_i = int(pos)
        hi_i = min(len(xs_sorted) - 1, lo_i + 1)
        frac = pos - lo_i
        return float(xs_sorted[lo_i] * (1 - frac) + xs_sorted[hi_i] * frac)

    def _valid_bar(self, b) -> bool:
        try:
            o, h, l, c = float(b.open), float(b.high), float(b.low), float(b.close)
        except Exception:
            return False
        if not (isfinite(o) and isfinite(h) and isfinite(l) and isfinite(c)):
            return False
        if min(o, h, l, c) <= 0:
            return False
        if h < l:
            return False
        if h < max(o, c):
            return False
        if l > min(o, c):
            return False
        return True

    def _draw_candles(self, bars: list, *, title: str, scale: str) -> None:
        self.canvas.delete("all")
        w = max(1, int(self.canvas.winfo_width()))
        h = max(1, int(self.canvas.winfo_height()))

        pad_left, pad_right, pad_top, pad_bottom = 60, 20, 30, 30
        plot_w = max(10, w - pad_left - pad_right)
        plot_h = max(10, h - pad_top - pad_bottom)

        bars_ok = [b for b in bars if self._valid_bar(b)]
        invalid_n = len(bars) - len(bars_ok)
        if not bars_ok:
            bars_ok = bars
            invalid_n = 0

        highs = [float(b.high) for b in bars_ok]
        lows = [float(b.low) for b in bars_ok]
        full_hi = max(highs)
        full_lo = min(lows)

        scale = (scale or "robust").strip().lower()
        if scale == "robust" and len(bars_ok) >= 80:
            prices: list[float] = []
            for b in bars_ok:
                prices.extend([float(b.open), float(b.high), float(b.low), float(b.close)])
            prices = [p for p in prices if isfinite(p) and p > 0]
            prices.sort()
            lo = self._quantile(prices, 0.01)
            hi = self._quantile(prices, 0.99)
            if hi <= lo:
                lo, hi = full_lo, full_hi
        else:
            lo, hi = full_lo, full_hi
        if hi == lo:
            hi = lo + 1e-6

        def y(price: float) -> float:
            return pad_top + (hi - price) / (hi - lo) * plot_h

        # title
        info = []
        if scale == "robust":
            info.append("scale=robust(1-99%)")
        else:
            info.append("scale=full")
        if invalid_n:
            info.append(f"invalid={invalid_n}")
        self.canvas.create_text(pad_left, 10, anchor="nw", text=title + "  " + " ".join(info), fill="black")

        # axes
        self.canvas.create_line(pad_left, pad_top, pad_left, pad_top + plot_h, fill="#999")
        self.canvas.create_line(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h, fill="#999")

        # y labels (3 ticks)
        for t in range(4):
            p = lo + (hi - lo) * t / 3
            yy = y(p)
            self.canvas.create_line(pad_left - 4, yy, pad_left, yy, fill="#999")
            self.canvas.create_text(pad_left - 8, yy, anchor="e", text=f"{p:.2f}", fill="#444")

        n = len(bars_ok)
        candle_w = max(2, int(plot_w / max(n, 1) * 0.6))
        step = plot_w / max(n, 1)

        clipped = 0
        for i, b in enumerate(bars_ok):
            cx = pad_left + (i + 0.5) * step
            color = "#e74c3c" if float(b.close) >= float(b.open) else "#2ecc71"
            o = float(b.open)
            c = float(b.close)
            hi_b = float(b.high)
            lo_b = float(b.low)
            # Clip for rendering when using robust scale to avoid outliers stretching the whole chart.
            if scale == "robust":
                if lo_b < lo or hi_b > hi or o < lo or o > hi or c < lo or c > hi:
                    clipped += 1
                lo_r = max(lo, min(hi, lo_b))
                hi_r = max(lo, min(hi, hi_b))
                o_r = max(lo, min(hi, o))
                c_r = max(lo, min(hi, c))
            else:
                lo_r, hi_r, o_r, c_r = lo_b, hi_b, o, c
            # wick
            self.canvas.create_line(cx, y(lo_r), cx, y(hi_r), fill=color)
            # body
            y1 = y(o_r)
            y2 = y(c_r)
            top = min(y1, y2)
            bottom = max(y1, y2)
            if bottom - top < 1:
                bottom = top + 1
            self.canvas.create_rectangle(cx - candle_w / 2, top, cx + candle_w / 2, bottom, outline=color, fill=color)

            # time labels every ~10 candles
            if i == 0 or i == n - 1 or (n > 20 and i % max(1, n // 10) == 0):
                self.canvas.create_text(cx, pad_top + plot_h + 12, anchor="n", text=b.ts.strftime("%H:%M"), fill="#444")

        if scale == "robust" and clipped:
            self.parent._log(f"kline clipped outliers={clipped} lo={lo:.4f} hi={hi:.4f} full_lo={full_lo:.4f} full_hi={full_hi:.4f}")
        if invalid_n:
            self.parent._log(f"kline dropped invalid bars={invalid_n}")


class BacktestWindow(tk.Toplevel):
    def __init__(self, parent: App) -> None:
        super().__init__(parent)
        self.title("Backtest")
        self.geometry("980x640")
        self.transient(parent)

        self.parent = parent
        self._trades_limit = 200

        self.var_symbol = tk.StringVar(value="")
        self.var_entry_mode = tk.StringVar(value="entry_mid")
        self.var_fill_bars = tk.StringVar(value="1")
        self.var_hold_bars = tk.StringVar(value="12")
        self.var_tp_level = tk.StringVar(value="1")
        self.var_exit_priority = tk.StringVar(value="stop_first")
        self.var_slippage_bps = tk.StringVar(value="0")
        self.var_position_cash = tk.StringVar(value="10000")
        self.var_fee_buy_cny = tk.StringVar(value="5")
        self.var_fee_sell_cny = tk.StringVar(value="6")

        self.var_lookback = tk.StringVar(value=parent.var_lookback.get() or "20")
        self.var_vol_factor = tk.StringVar(value=parent.var_vol_factor.get() or "1.5")
        self.var_atr_k = tk.StringVar(value="0.3")
        self.var_pct_buffer = tk.StringVar(value="0.002")
        self.var_swing_lookback = tk.StringVar(value="20")

        self.var_optimize = tk.BooleanVar(value=False)
        self.var_metric = tk.StringVar(value="avg_return")
        self.var_lookback_grid = tk.StringVar(value="10,15,20,25,30")
        self.var_vol_factor_grid = tk.StringVar(value="1.2,1.4,1.6,1.8,2.0")

        self.var_write_csv = tk.BooleanVar(value=False)
        self.var_trades_csv = tk.StringVar(value=str(parent.repo_root / "data" / "backtest_trades.csv"))

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Symbol (optional)").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.var_symbol, width=14).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(top, text="Empty => watchlist (Group/Limit in main)").grid(row=0, column=2, columnspan=4, sticky="w")

        ttk.Label(top, text="EntryMode").grid(row=0, column=6, sticky="w")
        ttk.Combobox(
            top,
            textvariable=self.var_entry_mode,
            values=["entry_mid", "entry_low", "entry_high", "trigger"],
            width=10,
            state="readonly",
        ).grid(row=0, column=7, sticky="w", padx=6)

        ttk.Label(top, text="Lookback").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_lookback, width=8).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="VolFactor").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_vol_factor, width=8).grid(row=1, column=3, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="ATR k").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_atr_k, width=8).grid(row=1, column=5, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="PctBuffer").grid(row=1, column=6, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_pct_buffer, width=8).grid(row=1, column=7, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(top, text="SwingLB").grid(row=1, column=8, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_swing_lookback, width=8).grid(row=1, column=9, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(top, text="FillBars").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_fill_bars, width=8).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="HoldBars").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_hold_bars, width=8).grid(row=2, column=3, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="TP").grid(row=2, column=4, sticky="w", pady=(6, 0))
        ttk.Combobox(top, textvariable=self.var_tp_level, values=["1", "2"], width=5, state="readonly").grid(
            row=2, column=5, sticky="w", padx=6, pady=(6, 0)
        )
        ttk.Label(top, text="Exit").grid(row=2, column=6, sticky="w", pady=(6, 0))
        ttk.Combobox(top, textvariable=self.var_exit_priority, values=["stop_first", "tp_first"], width=10, state="readonly").grid(
            row=2, column=7, sticky="w", padx=6, pady=(6, 0)
        )

        ttk.Label(top, text="T+1").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(top, text="Enforced").grid(row=3, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="PosCash(CNY)").grid(row=3, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_position_cash, width=10).grid(row=3, column=3, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="BuyFee(CNY)").grid(row=3, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_fee_buy_cny, width=8).grid(row=3, column=5, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="SellFee(CNY)").grid(row=3, column=6, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_fee_sell_cny, width=8).grid(row=3, column=7, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(top, text="Slippage bps").grid(row=3, column=8, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_slippage_bps, width=8).grid(row=3, column=9, sticky="w", padx=6, pady=(6, 0))

        ttk.Checkbutton(top, text="Optimize", variable=self.var_optimize, command=self._toggle_opt).grid(
            row=4, column=6, sticky="w", pady=(6, 0)
        )
        ttk.Label(top, text="Metric").grid(row=4, column=7, sticky="w", pady=(6, 0))
        self.metric_combo = ttk.Combobox(
            top,
            textvariable=self.var_metric,
            values=["avg_return", "win_rate", "profit_factor", "avg_r"],
            width=12,
            state="readonly",
        )
        self.metric_combo.grid(row=4, column=8, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(top, text="Lookback grid").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.lookback_grid_entry = ttk.Entry(top, textvariable=self.var_lookback_grid, width=22)
        self.lookback_grid_entry.grid(row=5, column=1, columnspan=2, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(top, text="VolFactor grid").grid(row=5, column=3, sticky="w", pady=(6, 0))
        self.vol_grid_entry = ttk.Entry(top, textvariable=self.var_vol_factor_grid, width=22)
        self.vol_grid_entry.grid(row=5, column=4, columnspan=2, sticky="w", padx=6, pady=(6, 0))

        ttk.Checkbutton(top, text="Write CSV", variable=self.var_write_csv).grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_trades_csv, width=40).grid(row=6, column=1, columnspan=4, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(top, text="Uses Start/End in main (enable Use Start/End)").grid(
            row=6, column=5, columnspan=4, sticky="w", pady=(6, 0)
        )

        btns = ttk.Frame(top)
        btns.grid(row=0, column=10, rowspan=6, padx=(12, 0), sticky="ns")
        ttk.Button(btns, text="Run Backtest", command=self._on_run).pack(fill="x", pady=2)
        ttk.Button(btns, text="Clear", command=self._clear_results).pack(fill="x", pady=2)

        mid = ttk.PanedWindow(self, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=2)
        mid.add(right, weight=3)

        ttk.Label(left, text="Summary").pack(anchor="w")
        self.summary_text = tk.Text(left, height=18)
        self.summary_text.pack(fill="both", expand=True)

        ttk.Label(right, text=f"Trades preview (first {self._trades_limit})").pack(anchor="w")
        self.trades_tree = ttk.Treeview(
            right,
            columns=("symbol", "entry_time", "exit_time", "return", "outcome"),
            show="headings",
            height=16,
        )
        for col, w in [
            ("symbol", 80),
            ("entry_time", 160),
            ("exit_time", 160),
            ("return", 90),
            ("outcome", 80),
        ]:
            self.trades_tree.heading(col, text=col)
            self.trades_tree.column(col, width=w, anchor="w")
        self.trades_tree.pack(fill="both", expand=True)

        self._toggle_opt()

    def _toggle_opt(self) -> None:
        enabled = bool(self.var_optimize.get())
        state = "normal" if enabled else "disabled"
        self.lookback_grid_entry.configure(state=state)
        self.vol_grid_entry.configure(state=state)
        self.metric_combo.configure(state="readonly" if enabled else "disabled")

    def _parse_int(self, raw: str, default: int) -> int:
        raw = (raw or "").strip()
        if raw == "":
            return default
        return int(raw)

    def _parse_float(self, raw: str, default: float) -> float:
        raw = (raw or "").strip()
        if raw == "":
            return default
        return float(raw)

    def _parse_grid_int(self, value: str) -> list[int]:
        value = value.strip()
        if ":" in value:
            parts = value.split(":")
            if len(parts) == 3:
                start, stop, step = (int(p) for p in parts)
                if step <= 0:
                    raise ValueError("grid step must be > 0")
                return list(range(start, stop + 1, step))
        return [int(v.strip()) for v in value.split(",") if v.strip()]

    def _parse_grid_float(self, value: str) -> list[float]:
        value = value.strip()
        if ":" in value:
            parts = value.split(":")
            if len(parts) == 3:
                start, stop, step = (float(p) for p in parts)
                if step <= 0:
                    raise ValueError("grid step must be > 0")
                out: list[float] = []
                cur = start
                while cur <= stop + 1e-9:
                    out.append(round(cur, 6))
                    cur += step
                return out
        return [float(v.strip()) for v in value.split(",") if v.strip()]

    def _format_summary(self, label: str, summary) -> str:
        pf = summary.profit_factor
        pf_s = "inf" if pf == float("inf") else f"{pf:.3f}" if pf is not None else "na"
        avg_r = f"{summary.avg_r:.3f}" if summary.avg_r is not None else "na"
        avg_win = f"{summary.avg_win:.4f}" if summary.avg_win is not None else "na"
        avg_loss = f"{summary.avg_loss:.4f}" if summary.avg_loss is not None else "na"
        expectancy = f"{summary.expectancy:.4f}" if summary.expectancy is not None else "na"
        return (
            f"{label} trades={len(summary.trades)} wins={summary.wins} "
            f"win_rate={summary.win_rate:.2%} avg_return={summary.avg_return:.4f} "
            f"avg_r={avg_r} avg_win={avg_win} avg_loss={avg_loss} expectancy={expectancy} "
            f"profit_factor={pf_s} max_dd={summary.max_drawdown:.4f} "
            f"signals={summary.signals} skipped={summary.skipped}"
        )

    def _clear_results(self) -> None:
        self.summary_text.delete("1.0", "end")
        self.trades_tree.delete(*self.trades_tree.get_children())

    def _set_results(self, summary_lines: list[str], trades: list) -> None:
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("end", "\n".join(summary_lines) + "\n")
        self.trades_tree.delete(*self.trades_tree.get_children())
        for t in trades[: self._trades_limit]:
            self.trades_tree.insert(
                "",
                "end",
                values=(
                    t.symbol,
                    t.entry_time.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M"),
                    t.exit_time.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M"),
                    f"{t.return_pct:.4f}",
                    t.outcome,
                ),
            )

    def _on_run(self) -> None:
        try:
            self.parent._ensure_provider()
            fixed = self.parent._snapshot_window()
            if fixed is None:
                window_minutes = self.parent._snapshot_int(self.parent.var_window, 60)
                start, end = self.parent._window_now(window_minutes)
            else:
                start, end = fixed

            symbol = self.var_symbol.get().strip().upper()
            if symbol:
                symbols = [symbol]
            else:
                symbols = [s for s, _g, _e, _n in self.parent._snapshot_symbols()]
            if not symbols:
                raise RuntimeError("no symbols to backtest")

            params = BreakoutParams(
                lookback=self._parse_int(self.var_lookback.get(), 20),
                vol_factor=self._parse_float(self.var_vol_factor.get(), 1.5),
                atr_buffer_k=self._parse_float(self.var_atr_k.get(), 0.3),
                pct_buffer=self._parse_float(self.var_pct_buffer.get(), 0.002),
                swing_lookback=self._parse_int(self.var_swing_lookback.get(), 20),
            )

            fill_bars = self._parse_int(self.var_fill_bars.get(), 1)
            hold_bars = self._parse_int(self.var_hold_bars.get(), 12)
            tp_level = self._parse_int(self.var_tp_level.get(), 1)
            exit_priority = self.var_exit_priority.get().strip() or "stop_first"
            entry_mode = self.var_entry_mode.get().strip() or "entry_mid"
            slippage_bps = self._parse_float(self.var_slippage_bps.get(), 0.0)
            position_cash_cny = self._parse_float(self.var_position_cash.get(), 10000.0)
            fee_buy_cny = self._parse_float(self.var_fee_buy_cny.get(), 5.0)
            fee_sell_cny = self._parse_float(self.var_fee_sell_cny.get(), 6.0)

            optimize = bool(self.var_optimize.get())
            metric = self.var_metric.get().strip() or "avg_return"
            lookback_grid = self._parse_grid_int(self.var_lookback_grid.get()) if optimize else []
            vol_grid = self._parse_grid_float(self.var_vol_factor_grid.get()) if optimize else []
            if optimize and (not lookback_grid or not vol_grid):
                raise RuntimeError("grid values are required for optimization")

            write_csv = bool(self.var_write_csv.get())
            trades_csv = Path(self.var_trades_csv.get().strip()) if write_csv else None
            self.parent._log(
                f"backtest params start={start.isoformat()} end={end.isoformat()} "
                f"symbols={len(symbols)} entry_mode={entry_mode} fill_bars={fill_bars} "
                f"hold_bars={hold_bars} tp_level={tp_level} exit_priority={exit_priority} "
                f"t_plus_one=True position_cash_cny={position_cash_cny} fee_buy_cny={fee_buy_cny} fee_sell_cny={fee_sell_cny} "
                f"slippage_bps={slippage_bps} optimize={optimize} "
                f"metric={metric} write_csv={write_csv}"
            )

        except Exception as e:
            self.parent._notify_error("Backtest", str(e))
            return

        self._clear_results()
        self.parent._log("clicked: Backtest")

        def task() -> None:
            try:
                bars_by_symbol: dict[str, list] = {}
                for sym in symbols:
                    bars = self.parent.data_service.get_bars(sym, "5m", start, end)
                    if not bars:
                        self.parent._log(f"backtest skip {sym}: no bars")
                        continue
                    bars_by_symbol[sym] = bars

                if not bars_by_symbol:
                    raise RuntimeError("no bars loaded")

                summary_lines: list[str] = []
                trades: list = []

                if optimize:
                    result = optimize_breakout_5m(
                        bars_by_symbol=bars_by_symbol,
                        lookbacks=lookback_grid,
                        vol_factors=vol_grid,
                        metric=metric,
                        base_params=params,
                        fill_bars=fill_bars,
                        hold_bars=hold_bars,
                        tp_level=tp_level,
                        exit_priority=exit_priority,
                        entry_mode=entry_mode,
                        slippage_bps=slippage_bps,
                        fee_buy_cny=fee_buy_cny,
                        fee_sell_cny=fee_sell_cny,
                        position_cash_cny=position_cash_cny,
                    )
                    summary_lines.append(f"best metric={result.metric} value={result.best_value:.4f} params={result.best_params}")
                    summary_lines.append(self._format_summary("summary ALL", result.summary))
                    trades = result.summary.trades
                else:
                    all_trades = []
                    total_signals = 0
                    total_skipped = 0
                    for sym, bars in bars_by_symbol.items():
                        summary = backtest_breakout_5m(
                            symbol=sym,
                            bars_5m=bars,
                            params=params,
                            fill_bars=fill_bars,
                            hold_bars=hold_bars,
                            tp_level=tp_level,
                            exit_priority=exit_priority,
                            entry_mode=entry_mode,
                            slippage_bps=slippage_bps,
                            fee_buy_cny=fee_buy_cny,
                            fee_sell_cny=fee_sell_cny,
                            position_cash_cny=position_cash_cny,
                        )
                        summary_lines.append(self._format_summary(f"summary {sym}", summary))
                        all_trades.extend(summary.trades)
                        total_signals += summary.signals
                        total_skipped += summary.skipped

                    summary_all = summarize_trades(
                        scope="ALL",
                        trades=all_trades,
                        signals=total_signals,
                        skipped=total_skipped,
                    )
                    summary_lines.append(self._format_summary("summary ALL", summary_all))
                    trades = all_trades

                if trades_csv is not None:
                    import csv

                    trades_csv.parent.mkdir(parents=True, exist_ok=True)
                    with trades_csv.open("w", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        w.writerow(
                            [
                                "symbol",
                                "signal_time",
                                "entry_time",
                                "exit_time",
                                "entry_price",
                                "exit_price",
                                "return_pct",
                                "r_multiple",
                                "outcome",
                                "entry_mode",
                                "slippage_bps",
                                "fee_buy_cny",
                                "fee_sell_cny",
                                "position_cash_cny",
                                "shares",
                                "entry_notional_cny",
                                "exit_notional_cny",
                                "net_pnl_cny",
                                "fill_bars",
                                "hold_bars",
                                "tp_level",
                            ]
                        )
                        for t in trades:
                            w.writerow(
                                [
                                    t.symbol,
                                    t.signal_time.isoformat(),
                                    t.entry_time.isoformat(),
                                    t.exit_time.isoformat(),
                                    f"{t.entry_price:.6f}",
                                    f"{t.exit_price:.6f}",
                                    f"{t.return_pct:.6f}",
                                    "" if t.r_multiple is None else f"{t.r_multiple:.6f}",
                                    t.outcome,
                                    t.entry_mode,
                                    f"{t.slippage_bps:.4f}",
                                    f"{t.fee_buy_cny:.2f}",
                                    f"{t.fee_sell_cny:.2f}",
                                    f"{t.position_cash_cny:.2f}",
                                    t.shares,
                                    f"{t.entry_notional_cny:.2f}",
                                    f"{t.exit_notional_cny:.2f}",
                                    f"{t.net_pnl_cny:.2f}",
                                    t.fill_bars,
                                    t.hold_bars,
                                    t.tp_level,
                                ]
                            )
                    self.parent._log(f"backtest trades_csv={trades_csv}")

                self.after(0, lambda: self._set_results(summary_lines, trades))
            except Exception as e:
                self.parent._log(f"ERROR backtest: {e}")
                self.parent._log(traceback.format_exc())
                self.after(0, lambda: self.parent._notify_error("Backtest", str(e)))

        self.parent._run_in_worker(task)


if __name__ == "__main__":
    raise SystemExit(main())
