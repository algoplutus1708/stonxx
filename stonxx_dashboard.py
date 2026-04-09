"""
stonxx_dashboard.py
===================
Live terminal dashboard for the stonxx NiftySwingAlpha paper trading bot.

Run in a SEPARATE terminal window while the bot is running:
    python stonxx_dashboard.py

Reads:
  - bot_state.json      → active trades (Memory Bank)
  - paper_trades.csv    → full trade history
  - logs/               → latest log file for signal parsing

Refreshes every 15 seconds automatically.
"""

import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import pytz
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Config ────────────────────────────────────────────────────────────────────
STATE_FILE       = "bot_state.json"
PAPER_TRADE_FILE = "paper_trades.csv"
LOGS_DIR         = "logs"
REFRESH_SECONDS  = 15
IST              = pytz.timezone("Asia/Kolkata")

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ist_now() -> datetime:
    return datetime.now(IST)


def _fmt_ts(ts_str: str) -> str:
    """Return a friendly elapsed-time string from a CSV timestamp."""
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - dt
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins}m ago"
        hrs = mins // 60
        return f"{hrs}h {mins % 60}m ago"
    except Exception:
        return ts_str


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"active_trades": {}}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"active_trades": {}}


def _load_paper_trades() -> list[dict]:
    if not os.path.exists(PAPER_TRADE_FILE):
        return []
    try:
        with open(PAPER_TRADE_FILE, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return []


def _read_last_log_lines(n: int = 80) -> list[str]:
    """Read the last n lines from the most recent log file."""
    log_dir = Path(LOGS_DIR)
    if not log_dir.exists():
        return []
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return []
    try:
        with open(logs[0], errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return []


def _parse_signals_from_log(lines: list[str]) -> list[dict]:
    """Extract the most recent ML signal line per symbol from log tail."""
    # Pattern: [SYMBOL] Logic check: Short=X.XXX | Hold=X.XXX | Long=X.XXX
    pattern = re.compile(
        r"\[(?P<sym>[A-Z0-9]+)\] Logic check: Short=(?P<short>\d+\.\d+) \| Hold=(?P<hold>\d+\.\d+) \| Long=(?P<long>\d+\.\d+)"
    )
    seen: dict[str, dict] = {}
    for line in lines:
        m = pattern.search(line)
        if m:
            seen[m.group("sym")] = {
                "symbol": m.group("sym"),
                "short":  float(m.group("short")),
                "hold":   float(m.group("hold")),
                "long":   float(m.group("long")),
            }
    return list(seen.values())


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return (9, 15) <= hm < (15, 30)


# ── UI builders ───────────────────────────────────────────────────────────────

def make_header() -> Panel:
    now = _ist_now().strftime("%A, %d %b %Y  %I:%M:%S %p IST")
    market_tag = (
        Text(" ● MARKET OPEN ", style="bold green on dark_green")
        if _is_market_open()
        else Text(" ● MARKET CLOSED ", style="bold white on grey30")
    )
    title = Text()
    title.append("  STONXX  ", style="bold bright_cyan on grey11")
    title.append("  NiftySwingAlpha  Paper Trader Dashboard  ", style="bold white on grey11")
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="center")
    grid.add_column(justify="right")
    grid.add_row(title, "", Text(now, style="dim white"))
    return Panel(grid, style="grey11", padding=(0, 1))


def make_status_bar() -> Panel:
    market_color = "bright_green" if _is_market_open() else "bright_red"
    market_label = "OPEN ●" if _is_market_open() else "CLOSED ●"

    grid = Table.grid(expand=True, padding=(0, 4))
    grid.add_column(justify="center")
    grid.add_column(justify="center")
    grid.add_column(justify="center")
    grid.add_column(justify="center")

    grid.add_row(
        Text("NSE SESSION", style="dim"),
        Text("STRATEGY", style="dim"),
        Text("MODE", style="dim"),
        Text("REFRESH", style="dim"),
    )
    grid.add_row(
        Text(market_label, style=f"bold {market_color}"),
        Text("stonxx (NiftySwingAlpha)", style="bold bright_cyan"),
        Text("PAPER TRADING", style="bold yellow"),
        Text(f"every {REFRESH_SECONDS}s", style="dim white"),
    )
    return Panel(grid, style="grey15", padding=(0, 2))


def make_signals_table(signals: list[dict]) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold bright_cyan",
        style="grey15",
        expand=True,
        padding=(0, 2),
    )
    table.add_column("Symbol",    style="bold white",  min_width=12)
    table.add_column("Short %",   justify="right",     min_width=10)
    table.add_column("Hold %",    justify="right",     min_width=10)
    table.add_column("Long %",    justify="right",     min_width=10)
    table.add_column("Signal",    justify="center",    min_width=14)
    table.add_column("Conviction",justify="center",    min_width=12)

    THRESHOLD = 0.45

    if not signals:
        table.add_row("[dim]Waiting for first scan...[/dim]", "", "", "", "", "")
    else:
        for s in signals:
            sym   = s["symbol"]
            short = s["short"]
            hold  = s["hold"]
            long_ = s["long"]

            # Determine signal
            if long_ > THRESHOLD:
                signal_text = Text("▲  BUY",  style="bold bright_green")
                conviction  = Text(f"{long_:.1%}", style="bright_green")
            elif short > THRESHOLD:
                signal_text = Text("▼  SHORT", style="bold bright_red")
                conviction  = Text(f"{short:.1%}", style="bright_red")
            else:
                signal_text = Text("─  HOLD", style="dim white")
                conviction  = Text(f"{hold:.1%}", style="dim")

            # Highlight the dominant probability
            def pct(v, dominant):
                s = f"{v:.1%}"
                return Text(s, style="bold bright_yellow") if dominant else Text(s, style="dim white")

            best = max(short, hold, long_)
            table.add_row(
                Text(sym, style="bold white"),
                pct(short, short == best),
                pct(hold,  hold  == best),
                pct(long_, long_ == best),
                signal_text,
                conviction,
            )

    return Panel(
        table,
        title="[bold bright_cyan] ML Signal Scanner [/bold bright_cyan]",
        border_style="cyan",
        padding=(0, 1),
    )


def make_active_trades_table(state: dict) -> Panel:
    trades = state.get("active_trades", {})
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold bright_green",
        style="grey15",
        expand=True,
        padding=(0, 2),
    )
    table.add_column("Symbol",      style="bold white",       min_width=12)
    table.add_column("Entry Price", justify="right",          min_width=12)
    table.add_column("Qty",         justify="right",          min_width=8)
    table.add_column("Value (est)", justify="right",          min_width=14)

    if not trades:
        table.add_row("[dim]No active trades tracked[/dim]", "", "", "")
    else:
        for sym, info in trades.items():
            price = info.get("fill_price", 0)
            qty   = info.get("quantity", 0)
            value = price * qty
            table.add_row(
                Text(sym, style="bold bright_green"),
                Text(f"₹{price:,.2f}", style="white"),
                Text(str(qty), style="white"),
                Text(f"₹{value:,.0f}", style="bold yellow"),
            )

    count = len(trades)
    title = f"[bold bright_green] Active Trades ({count}/3 max) [/bold bright_green]"
    return Panel(table, title=title, border_style="green", padding=(0, 1))


def make_paper_trades_table(trades: list[dict]) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold bright_yellow",
        style="grey15",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Time",     min_width=12)
    table.add_column("Symbol",   style="bold white", min_width=10)
    table.add_column("Dir",      justify="center",   min_width=7)
    table.add_column("Qty",      justify="right",    min_width=6)
    table.add_column("Entry",    justify="right",    min_width=10)
    table.add_column("TP",       justify="right",    min_width=10)
    table.add_column("SL",       justify="right",    min_width=10)

    recent = trades[-10:][::-1]  # last 10, newest first
    if not recent:
        table.add_row("[dim]No paper trades yet[/dim]", "", "", "", "", "", "")
    else:
        for t in recent:
            direction = t.get("Direction", "")
            dir_text  = (
                Text(f"▲ {direction}", style="bold bright_green")
                if direction == "BUY"
                else Text(f"▼ {direction}", style="bold bright_red")
            )
            try:
                entry = float(t.get("Entry", 0))
                tp    = float(t.get("TakeProfit", 0))
                sl    = float(t.get("StopLoss", 0))
            except (ValueError, TypeError):
                entry = tp = sl = 0.0

            table.add_row(
                Text(_fmt_ts(t.get("Timestamp", "")), style="dim white"),
                Text(t.get("Asset", ""), style="bold white"),
                dir_text,
                Text(t.get("Quantity", ""), style="white"),
                Text(f"₹{entry:,.2f}", style="white"),
                Text(f"₹{tp:,.2f}",    style="dim bright_green"),
                Text(f"₹{sl:,.2f}",    style="dim bright_red"),
            )

    total = len(trades)
    title = f"[bold bright_yellow] Paper Trade Log ({total} total, showing last 10) [/bold bright_yellow]"
    return Panel(table, title=title, border_style="yellow", padding=(0, 1))


def make_footer() -> Text:
    t = Text(justify="center")
    t.append("  Q  ", style="bold black on white")
    t.append(" Quit    ", style="dim white")
    t.append("  Ctrl+C  ", style="bold black on white")
    t.append(" Stop    ", style="dim white")
    t.append("  Bot log: ", style="dim white")
    t.append("logs/", style="bold cyan")
    t.append("    Paper trades: ", style="dim white")
    t.append("paper_trades.csv", style="bold yellow")
    return t


# ── Main render ───────────────────────────────────────────────────────────────

def build_display() -> Layout:
    state       = _load_state()
    paper_trades = _load_paper_trades()
    log_lines   = _read_last_log_lines(100)
    signals     = _parse_signals_from_log(log_lines)

    layout = Layout()
    layout.split_column(
        Layout(make_header(),              name="header",  size=3),
        Layout(make_status_bar(),          name="status",  size=5),
        Layout(make_signals_table(signals),name="signals", size=len(signals) + 6 if signals else 7),
        Layout(name="middle",              ratio=1),
        Layout(make_footer(),             name="footer",  size=1),
    )
    layout["middle"].split_row(
        Layout(make_active_trades_table(state),      name="active",  ratio=1),
        Layout(make_paper_trades_table(paper_trades),name="history", ratio=2),
    )
    return layout


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    console.clear()
    console.print(
        Panel(
            Align.center(
                Text("STONXX Dashboard loading...", style="bold bright_cyan"),
                vertical="middle",
            ),
            style="grey11",
            height=5,
        )
    )
    time.sleep(1)

    try:
        with Live(
            build_display(),
            refresh_per_second=1,
            screen=True,
            console=console,
        ) as live:
            tick = 0
            while True:
                time.sleep(1)
                tick += 1
                if tick % REFRESH_SECONDS == 0:
                    live.update(build_display())
    except KeyboardInterrupt:
        console.clear()
        console.print(
            Panel(
                Align.center(Text("Dashboard stopped. Bot is still running.", style="bold yellow")),
                style="grey11",
                height=3,
            )
        )
