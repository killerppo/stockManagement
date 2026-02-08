from __future__ import annotations

import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta
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
from stock_management.data.providers import EastmoneyKlineProvider  # noqa: E402
from stock_management.data.service import DataService  # noqa: E402
from stock_management.indicators import IndicatorParams  # noqa: E402
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
        self.geometry("1100x700")

        self._log_queue: Queue[str] = Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._status_var = tk.StringVar(value="Ready")

        self.repo_root = REPO_ROOT
        self.watchlist_path = self.repo_root / "config" / "watchlist.csv"
        self.data_dir = self.repo_root / "data"
        self.signals_db = self.data_dir / "signals.sqlite"

        provider = EastmoneyKlineProvider()
        self.data_service = DataService.with_default_store(provider=provider, data_dir=self.data_dir)
        self.signal_store = SQLiteSignalStore(self.signals_db)

        self._signals_cache: dict[int, object] = {}
        self._watch_items: list[WatchItem] = []
        self._build_ui()
        self.after(100, self._drain_logs)
        self._load_watchlist()
        self._reload_signals()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

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

        ttk.Label(top, text="Group").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.var_group, width=12).grid(row=0, column=1, padx=6)

        ttk.Label(top, text="Limit").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.var_limit, width=6).grid(row=0, column=3, padx=6)

        ttk.Label(top, text="Window(min)").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.var_window, width=8).grid(row=0, column=5, padx=6)

        ttk.Label(top, text="SignalWindow(min)").grid(row=0, column=6, sticky="w")
        ttk.Entry(top, textvariable=self.var_signal_window, width=10).grid(row=0, column=7, padx=6)

        ttk.Label(top, text="Interval(s)").grid(row=0, column=8, sticky="w")
        ttk.Entry(top, textvariable=self.var_interval, width=8).grid(row=0, column=9, padx=6)

        ttk.Label(top, text="Lookback").grid(row=1, column=8, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_lookback, width=8).grid(row=1, column=9, padx=6, pady=(6, 0))

        ttk.Label(top, text="VolFactor").grid(row=2, column=8, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.var_vol_factor, width=8).grid(row=2, column=9, padx=6, pady=(6, 0))

        ttk.Label(top, text="Start").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.start_entry = ttk.Entry(top, textvariable=self.var_start, width=28, state="disabled")
        self.start_entry.grid(row=1, column=1, columnspan=2, sticky="we", padx=6, pady=(6, 0))
        ttk.Button(top, text="Pick", command=lambda: self._pick_datetime(self.var_start, title="Pick Start")).grid(row=1, column=3, sticky="w", pady=(6, 0))

        ttk.Label(top, text="End").grid(row=1, column=4, sticky="w", pady=(6, 0))
        self.end_entry = ttk.Entry(top, textvariable=self.var_end, width=28, state="disabled")
        self.end_entry.grid(row=1, column=5, columnspan=2, sticky="we", padx=6, pady=(6, 0))
        ttk.Button(top, text="Pick", command=lambda: self._pick_datetime(self.var_end, title="Pick End")).grid(row=1, column=7, sticky="w", pady=(6, 0))

        btns = ttk.Frame(top)
        btns.grid(row=0, column=10, rowspan=2, padx=(12, 0), sticky="ns")

        ttk.Button(btns, text="Reload Watchlist", command=self._load_watchlist).pack(fill="x", pady=2)
        ttk.Button(btns, text="Add Symbol", command=self._on_add_symbol).pack(fill="x", pady=2)
        ttk.Button(btns, text="Edit Selected", command=self._on_edit_symbol).pack(fill="x", pady=2)
        ttk.Button(btns, text="Delete Selected", command=self._on_delete_symbol).pack(fill="x", pady=2)
        ttk.Button(btns, text="Save Watchlist", command=self._on_save_watchlist).pack(fill="x", pady=2)
        ttk.Button(btns, text="Refresh Cache", command=self._on_refresh).pack(fill="x", pady=2)
        ttk.Button(btns, text="Scan Signals", command=self._on_scan).pack(fill="x", pady=2)
        ttk.Button(btns, text="Refresh+Scan", command=self._on_refresh_scan).pack(fill="x", pady=2)
        ttk.Button(btns, text="Reload Signals", command=self._reload_signals).pack(fill="x", pady=2)
        ttk.Button(btns, text="Show Kline", command=self._on_show_kline).pack(fill="x", pady=2)
        ttk.Button(btns, text="Start Loop", command=self._on_start_loop).pack(fill="x", pady=2)
        ttk.Button(btns, text="Stop", command=self._on_stop).pack(fill="x", pady=2)

        ttk.Checkbutton(top, text="Log signals to SQLite", variable=self.var_log_signals).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(top, text="Auto scan in loop", variable=self.var_auto_scan).grid(row=2, column=3, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(top, text="Use Start/End", variable=self.var_use_fixed, command=self._on_toggle_fixed).grid(row=2, column=6, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(top, text="Today 09:30-15:00", command=self._fill_today_session).grid(row=2, column=8, columnspan=2, sticky="w", pady=(6, 0))

        mid = ttk.PanedWindow(self, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=10, pady=8)

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=3)
        mid.add(right, weight=2)

        ttk.Label(left, text="Watchlist").pack(anchor="w")
        self.watch_tree = ttk.Treeview(
            left,
            columns=("symbol", "group", "enabled", "note", "last_ts", "last_close", "changes"),
            show="headings",
            height=18,
        )
        for col, w in [
            ("symbol", 95),
            ("group", 85),
            ("enabled", 65),
            ("note", 180),
            ("last_ts", 160),
            ("last_close", 85),
            ("changes", 70),
        ]:
            self.watch_tree.heading(col, text=col)
            self.watch_tree.column(col, width=w, anchor="w")
        self.watch_tree.pack(fill="both", expand=True)
        self.watch_tree.bind("<Double-1>", lambda _e: self._on_show_kline())

        ttk.Label(right, text="Recent Signals").pack(anchor="w")
        self.sig_tree = ttk.Treeview(
            right,
            columns=("ts", "symbol", "strategy", "dir", "score", "entry", "stop", "tp1", "tp2"),
            show="headings",
            height=18,
        )
        for col, w in [
            ("ts", 170),
            ("symbol", 90),
            ("strategy", 110),
            ("dir", 60),
            ("score", 55),
            ("entry", 120),
            ("stop", 90),
            ("tp1", 90),
            ("tp2", 90),
        ]:
            self.sig_tree.heading(col, text=col)
            self.sig_tree.column(col, width=w, anchor="w")
        self.sig_tree.pack(fill="both", expand=True)
        self.sig_tree.bind("<<TreeviewSelect>>", self._on_signal_select)

        ttk.Label(right, text="Signal Details").pack(anchor="w", pady=(6, 0))
        self.sig_details = tk.Text(right, height=10)
        self.sig_details.pack(fill="both", expand=False)

        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        ttk.Label(bottom, text="Log").pack(anchor="w")
        self.log_text = tk.Text(bottom, height=10)
        self.log_text.pack(fill="both", expand=True)

        status = ttk.Frame(self)
        status.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(status, textvariable=self._status_var).pack(anchor="w")

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
        state = "normal" if enabled else "disabled"
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)
        if not enabled:
            self.var_start.set("")
            self.var_end.set("")

    def _fill_today_session(self) -> None:
        now = _now_minute()
        day = now.date()
        start = datetime.combine(day, datetime.strptime("09:30", "%H:%M").time(), TZ_SHANGHAI)
        end = datetime.combine(day, datetime.strptime("15:00", "%H:%M").time(), TZ_SHANGHAI)
        self.var_use_fixed.set(True)
        self._on_toggle_fixed()
        self.var_start.set(_fmt_dt(start))
        self.var_end.set(_fmt_dt(end))

    def _pick_datetime(self, target_var: tk.StringVar, *, title: str) -> None:
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
        for sym, group, enabled, note in symbols:
            self.watch_tree.insert(
                "",
                "end",
                iid=sym,
                values=(sym, group or "", "1" if enabled else "0", note or "", "", "", ""),
            )
        self._log(f"watchlist loaded: {len(symbols)} symbols")

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
        item = self._prompt_watch_item("Add Symbol")
        if item is None:
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
        sym = self._selected_symbol()
        if not sym:
            self._notify_error("Delete Selected", "Select a symbol first")
            return
        if not messagebox.askyesno("Delete Selected", f"Delete {sym} from watchlist?"):
            return
        items = [i for i in load_watchlist(self.watchlist_path) if i.symbol.upper() != sym.upper()]
        self._watch_items = items
        save_watchlist(self._watch_items, self.watchlist_path)
        self._load_watchlist()

    def _on_save_watchlist(self) -> None:
        items = load_watchlist(self.watchlist_path)
        issues = validate_watchlist(items)
        if issues:
            self._notify_error("Save Watchlist", issues[0].message)
            return
        self._watch_items = items
        save_watchlist(self._watch_items, self.watchlist_path)
        self._log("watchlist saved")

    def _on_show_kline(self) -> None:
        sym = self._selected_symbol()
        if not sym:
            self._notify_error("Show Kline", "Select a symbol first")
            return
        KlineWindow(self, symbol=sym, data_service=self.data_service)

    def _reload_signals(self) -> None:
        self.sig_tree.delete(*self.sig_tree.get_children())
        self._signals_cache.clear()
        try:
            rows = self.signal_store.list_recent(limit=50)
        except Exception as e:
            self._log(f"ERROR load signals: {e}")
            return

        for r in rows:
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
            )
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
        self._log("stop requested")

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
            fixed_window = self._snapshot_window()
            symbols = self._snapshot_symbols()
            window_minutes = self._snapshot_int(self.var_window, 60)
        except Exception as e:
            self._notify_error("Refresh", str(e))
            return

        self._log("clicked: Refresh Cache")

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
            )

        self._run_in_worker(task)

    def _on_scan(self) -> None:
        try:
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
        lookback = self._snapshot_int(self.var_lookback, 20)
        vol_factor = float((self.var_vol_factor.get() or "1.5").strip())
        self._run_in_worker(
            lambda: self._scan_task(
                symbols=symbols,
                end=end,
                signal_window_minutes=signal_window,
                log_signals=log_signals,
                lookback=lookback,
                vol_factor=vol_factor,
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
    ) -> None:
        try:
            sig_start = end - timedelta(minutes=max(signal_window_minutes, 1))
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
                sigs = breakout_scan_5m(symbol=sym, bars_5m=bars_5m, ind_params=ind_params, params=strat_params)
                emitted += len(sigs)

                if log_signals and sigs:
                    stored += self.signal_store.insert_signals(sigs, strategy_id="breakout_5m_v1", params_snapshot=params_snapshot)

                self._log(f"[{idx}/{len(symbols)}] {sym} signals={len(sigs)}")

            self._log(f"scan done emitted={emitted} stored={stored}")
            self.after(0, self._reload_signals)
        except Exception as e:
            self._log(f"ERROR scan: {e}")
            self._log(traceback.format_exc())

    def _on_start_loop(self) -> None:
        try:
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

        ttk.Button(top, text="Refresh", command=self.refresh).grid(row=0, column=6, sticky="w", padx=(12, 0))

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
        except Exception as e:
            self.parent._notify_error("Kline", str(e))
            return

        start, end = self._window_for_chart(freq, bars_n)
        bars = self.data_service.get_bars(self.symbol, freq, start, end)
        if not bars:
            self.canvas.delete("all")
            self.canvas.create_text(20, 20, anchor="nw", text="No bars in range", fill="black")
            return

        # keep last N
        bars = bars[-bars_n:]
        self._draw_candles(bars, title=f"{self.symbol} {freq} {bars[0].ts:%Y-%m-%d %H:%M} .. {bars[-1].ts:%H:%M}")

    def _draw_candles(self, bars: list, *, title: str) -> None:
        self.canvas.delete("all")
        w = max(1, int(self.canvas.winfo_width()))
        h = max(1, int(self.canvas.winfo_height()))

        pad_left, pad_right, pad_top, pad_bottom = 60, 20, 30, 30
        plot_w = max(10, w - pad_left - pad_right)
        plot_h = max(10, h - pad_top - pad_bottom)

        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        hi = max(highs)
        lo = min(lows)
        if hi == lo:
            hi = lo + 1e-6

        def y(price: float) -> float:
            return pad_top + (hi - price) / (hi - lo) * plot_h

        # title
        self.canvas.create_text(pad_left, 10, anchor="nw", text=title, fill="black")

        # axes
        self.canvas.create_line(pad_left, pad_top, pad_left, pad_top + plot_h, fill="#999")
        self.canvas.create_line(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h, fill="#999")

        # y labels (3 ticks)
        for t in range(4):
            p = lo + (hi - lo) * t / 3
            yy = y(p)
            self.canvas.create_line(pad_left - 4, yy, pad_left, yy, fill="#999")
            self.canvas.create_text(pad_left - 8, yy, anchor="e", text=f"{p:.2f}", fill="#444")

        n = len(bars)
        candle_w = max(2, int(plot_w / max(n, 1) * 0.6))
        step = plot_w / max(n, 1)

        for i, b in enumerate(bars):
            cx = pad_left + (i + 0.5) * step
            color = "#e74c3c" if b.close >= b.open else "#2ecc71"
            # wick
            self.canvas.create_line(cx, y(b.low), cx, y(b.high), fill=color)
            # body
            y1 = y(b.open)
            y2 = y(b.close)
            top = min(y1, y2)
            bottom = max(y1, y2)
            if bottom - top < 1:
                bottom = top + 1
            self.canvas.create_rectangle(cx - candle_w / 2, top, cx + candle_w / 2, bottom, outline=color, fill=color)

            # time labels every ~10 candles
            if i == 0 or i == n - 1 or (n > 20 and i % max(1, n // 10) == 0):
                self.canvas.create_text(cx, pad_top + plot_h + 12, anchor="n", text=b.ts.strftime("%H:%M"), fill="#444")


if __name__ == "__main__":
    raise SystemExit(main())
