"""Build and serve the portal locally with production-like DB loading.

Vite's dev and preview servers are fine for ordinary static assets, but
this portal's browser SQLite path needs byte-range support for boards.db.
This helper builds the frontend, stages a current local boards.db into
dist/, serves dist/ with Range + COOP/COEP headers, and opens a browser.
"""

from __future__ import annotations

import argparse
import functools
import mimetypes
import os
import pathlib
import re
import socket
import subprocess
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


REPO = pathlib.Path(__file__).resolve().parents[1]
SITE_SRC = REPO / "site-src"
DIST = SITE_SRC / "dist"
BOARDS_DB = DIST / "boards.db"
MIME_OVERRIDES = {
    ".css": "text/css",
    ".db": "application/octet-stream",
    ".html": "text/html",
    ".js": "application/javascript",
    ".json": "application/json",
    ".mjs": "application/javascript",
    ".wasm": "application/wasm",
}


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Static file handler with single-range byte serving."""

    server_version = "FastLEDBoardsLocal/0.1"
    protocol_version = "HTTP/1.1"

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()

    def send_head(self):  # noqa: D401 - mirrors stdlib method name/shape
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith("/"):
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                new_parts = (parts[0], parts[1], parts[2] + "/", parts[3], parts[4])
                self.send_header("Location", urllib.parse.urlunsplit(new_parts))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            for index in ("index.html", "index.htm"):
                index_path = os.path.join(path, index)
                if os.path.isfile(index_path):
                    path = index_path
                    break
            else:
                return self.list_directory(path)

        ctype = self.guess_type(path)
        try:
            file_obj = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        try:
            size = os.fstat(file_obj.fileno()).st_size
            range_header = self.headers.get("Range")
            if range_header:
                parsed = _parse_range(range_header, size)
                if parsed is None:
                    file_obj.close()
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None

                start, end = parsed
                file_obj.seek(start)
                content_length = end - start + 1
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(content_length))
                self.send_header("Last-Modified", self.date_time_string(os.fstat(file_obj.fileno()).st_mtime))
                self.end_headers()
                return _LimitedReader(file_obj, content_length)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Last-Modified", self.date_time_string(os.fstat(file_obj.fileno()).st_mtime))
            self.end_headers()
            return file_obj
        except Exception:
            file_obj.close()
            raise


class _LimitedReader:
    def __init__(self, file_obj, remaining: int):
        self.file_obj = file_obj
        self.remaining = remaining

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if size < 0 or size > self.remaining:
            size = self.remaining
        data = self.file_obj.read(size)
        self.remaining -= len(data)
        return data

    def close(self) -> None:
        self.file_obj.close()


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or size < 0:
        return None

    start_s, end_s = match.groups()
    if not start_s and not end_s:
        return None

    if start_s:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    else:
        suffix_len = int(end_s)
        if suffix_len <= 0:
            return None
        start = max(size - suffix_len, 0)
        end = size - 1

    if start >= size or start > end:
        return None
    return start, min(end, size - 1)


def _run(cmd: list[str], cwd: pathlib.Path) -> None:
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def _find_port(host: str, requested: int) -> int:
    for port in range(requested, requested + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port found from {requested} to {requested + 99}")


def _prepare_dist(skip_build: bool, skip_db_rebuild: bool) -> None:
    if not skip_build:
        _run(["npm", "run", "build"], SITE_SRC)

    if not skip_db_rebuild:
        _run([sys.executable, str(REPO / "tools" / "rebuild_boards_local.py"), "--out", str(BOARDS_DB)], REPO)

    missing = [p for p in (DIST / "index.html", BOARDS_DB) if not p.exists()]
    if missing:
        names = ", ".join(str(p.relative_to(REPO)) for p in missing)
        raise FileNotFoundError(f"missing required local portal artifact(s): {names}")


def _configure_mime_types() -> None:
    for extension, mime_type in MIME_OVERRIDES.items():
        mimetypes.add_type(mime_type, extension, strict=True)
        mimetypes.add_type(mime_type, extension, strict=False)
    RangeRequestHandler.extensions_map.update(MIME_OVERRIDES)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and serve the boards portal locally with byte-range DB support.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser window")
    parser.add_argument("--skip-build", action="store_true", help="serve existing site-src/dist without running npm build")
    parser.add_argument(
        "--skip-db-rebuild",
        action="store_true",
        help="use existing site-src/dist/boards.db instead of rebuilding it",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_mime_types()

    args = parse_args(argv or sys.argv[1:])
    _prepare_dist(args.skip_build, args.skip_db_rebuild)

    port = _find_port(args.host, args.port)
    handler = functools.partial(RangeRequestHandler, directory=str(DIST))
    url = f"http://{args.host}:{port}/"

    with ThreadingHTTPServer((args.host, port), handler) as server:
        print(f"Serving FastLED/boards portal at {url}", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        if port != args.port:
            print(f"Requested port {args.port} was busy; using {port}.", flush=True)
        if args.no_open:
            print("Browser launch suppressed by --no-open.", flush=True)
        else:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping local portal server.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
