#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pywebview>=5.3",
# ]
# ///
"""Run the local portal demo in a blocking webview.

Usage:
  uv run --no-project --script tools/demo_webview.py
  uv run --no-project --script tools/demo_webview.py --port 5192 --timeout 120
  uv run --no-project --script tools/demo_webview.py --skip-build --skip-db-rebuild

The script starts tools/serve_portal_local.py with --no-open, waits for
the served URL, opens it in a native webview, then stops the server when
the webview closes or when the timeout is reached.
"""

from __future__ import annotations

import argparse
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import webview


REPO = Path(__file__).resolve().parents[1]
SERVE_SCRIPT = REPO / "tools" / "serve_portal_local.py"
URL_RE = re.compile(r"Serving FastLED/boards portal at (?P<url>https?://\S+)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build, serve, and show the FastLED/boards portal in a blocking webview.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="seconds to keep the webview open before closing it; use 0 to wait forever",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=180,
        help="seconds to wait for the local server to print its URL",
    )
    parser.add_argument("--title", default="FastLED/boards local demo")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-db-rebuild", action="store_true")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable pywebview debug mode",
    )
    return parser.parse_args(argv)


def server_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(SERVE_SCRIPT),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-open",
    ]
    if args.skip_build:
        cmd.append("--skip-build")
    if args.skip_db_rebuild:
        cmd.append("--skip-db-rebuild")
    return cmd


def start_server(args: argparse.Namespace) -> tuple[subprocess.Popen[str], str]:
    proc = subprocess.Popen(
        server_command(args),
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )

    lines: queue.Queue[str | None] = queue.Queue()

    def pump_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump_output, daemon=True).start()

    deadline = time.monotonic() + args.startup_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"local server exited early with code {proc.returncode}")
        try:
            line = lines.get(timeout=0.25)
        except queue.Empty:
            continue
        if line is None:
            continue
        match = URL_RE.search(line)
        if match:
            return proc, match.group("url")

    raise TimeoutError(f"local server did not become ready within {args.startup_timeout:g}s")


def stop_server(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def open_blocking_webview(args: argparse.Namespace, url: str) -> bool:
    """Open the webview and block.

    Returns True when the window was closed by timeout, False when the
    user closed the window first.
    """
    timed_out = threading.Event()
    closed = threading.Event()
    window = webview.create_window(
        args.title,
        url,
        width=args.width,
        height=args.height,
    )

    def timeout_close() -> None:
        if args.timeout <= 0:
            return
        if closed.wait(args.timeout):
            return
        timed_out.set()
        try:
            window.destroy()
        except Exception:
            pass

    threading.Thread(target=timeout_close, daemon=True).start()
    try:
        webview.start(debug=args.debug)
    finally:
        closed.set()
    return timed_out.is_set()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    proc: subprocess.Popen[str] | None = None
    try:
        proc, url = start_server(args)
        print(f"Opening demo webview: {url}", flush=True)
        timed_out = open_blocking_webview(args, url)
        if timed_out:
            print(f"Demo webview timed out after {args.timeout:g}s; stopping server.", flush=True)
        else:
            print("Demo webview closed; stopping server.", flush=True)
        return 0
    finally:
        if proc is not None:
            stop_server(proc)


if __name__ == "__main__":
    if not SERVE_SCRIPT.exists():
        print(f"error: missing {SERVE_SCRIPT}", file=sys.stderr)
        raise SystemExit(2)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
