"""Phase 0: discover how a Met Office Map Images order behaves.

Run once, by hand, with your own key:

    METOFFICE_KEY=... uv run scripts/discover.py <order-name>

It makes at most 20 requests (normally 5): the latest listing, then metadata
and data for one precipitation file and the land cover file. Everything is
written to discovery/ (git-ignored). The key is read from the environment,
sent only in the apikey header, and never printed or saved.
"""

from __future__ import annotations

import argparse
from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib import error, parse, request

from PIL import Image

BASE_URL = "https://data.hub.api.metoffice.gov.uk/map-images/1.0.0"
MAX_CALLS = 20
TIMEOUT = 60
OUT_DIR = Path("discovery")
FILE_ID = re.compile(r"^(?P<parameter>.+)_ts(?P<step>\d+)_(?P<run>\d{10})$")
# Header names worth keeping: rate limits, caching and content details.
KEEP_HEADERS = re.compile(
    r"^(content-|x-ratelimit|ratelimit|retry-after|etag|last-modified|date)", re.I
)


class Client:
    """A tiny synchronous client that counts and caps its calls."""

    def __init__(self, key: str, order: str) -> None:
        self._key = key
        self.order = order
        self.calls = 0
        self.log: list[dict[str, Any]] = []

    def get(self, path: str, accept: str) -> tuple[int, dict[str, str], bytes]:
        if self.calls >= MAX_CALLS:
            raise SystemExit(f"Stopping: reached the {MAX_CALLS}-call limit.")
        self.calls += 1
        url = f"{BASE_URL}/orders/{parse.quote(self.order, safe='')}/latest{path}"
        req = request.Request(url, headers={"apikey": self._key, "Accept": accept})
        try:
            with request.urlopen(req, timeout=TIMEOUT) as resp:
                status, headers, body = resp.status, dict(resp.headers), resp.read()
        except error.HTTPError as err:
            status, headers, body = err.code, dict(err.headers), err.read()
        kept = {k: v for k, v in headers.items() if KEEP_HEADERS.match(k)}
        self.log.append(
            {"call": self.calls, "path": path or "/", "status": status, "headers": kept}
        )
        print(f"  call {self.calls}: GET latest{path or ''} -> {status} ({len(body)} bytes)")
        return status, kept, body

    def scrub(self, data: bytes) -> bytes:
        """Remove the key if a response ever echoes it."""
        return data.replace(self._key.encode(), b"<redacted>")


def file_path(file_id: str) -> str:
    return "/" + parse.quote(file_id, safe="")


def save(name: str, data: bytes) -> Path:
    path = OUT_DIR / name.replace("/", "_").replace("+", "plus")
    path.write_bytes(data)
    return path


def describe_image(data: bytes) -> list[str]:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as err:  # report whatever went wrong
        return [f"    not a readable image: {err!r}"]
    lines = [
        f"    format {img.format}, size {img.size[0]}x{img.size[1]}, mode {img.mode}",
        f"    info keys: {sorted(img.info)}",
    ]
    bands = img.getbands()
    extrema = img.getextrema()
    if len(bands) == 1:
        extrema = (extrema,)
    for band, (low, high) in zip(bands, extrema, strict=True):
        lines.append(f"    band {band}: min {low}, max {high}")
    grey = img.convert("L") if img.mode not in ("L", "I", "I;16", "F") else img
    counts = Counter(grey.getdata())
    lines.append(f"    distinct grey values: {len(counts)}")
    lines.append(f"    most common (value: pixels): {counts.most_common(12)}")
    if img.mode in ("LA", "RGBA", "PA"):
        alpha = Counter(img.getchannel("A").getdata())
        lines.append(f"    alpha values (value: pixels): {alpha.most_common(6)}")
    return lines


def interesting_fields(meta: Any, prefix: str = "") -> list[str]:
    """List every leaf field, flagging ones that look like geometry."""
    hints = (
        "bound",
        "bbox",
        "extent",
        "proj",
        "crs",
        "srs",
        "lat",
        "lon",
        "east",
        "north",
        "west",
        "south",
        "x",
        "y",
        "width",
        "height",
        "resolution",
        "scale",
        "unit",
        "min",
        "max",
        "offset",
        "time",
        "date",
        "run",
        "step",
    )
    out: list[str] = []
    if isinstance(meta, dict):
        for key, value in meta.items():
            out += interesting_fields(value, f"{prefix}{key}.")
    elif isinstance(meta, list):
        for index, value in enumerate(meta[:20]):
            out += interesting_fields(value, f"{prefix}[{index}].")
    else:
        name = prefix.rstrip(".")
        flag = "*" if any(h in name.lower() for h in hints) else " "
        out.append(f"   {flag} {name} = {json.dumps(meta)[:200]}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("order", help="order name as the API spells it, e.g. uk-rain-hourly")
    parser.add_argument("--file", help="precipitation fileId to sample (default: first step >= 1)")
    args = parser.parse_args()

    key = os.environ.get("METOFFICE_KEY", "").strip()
    if not key:
        print("Set METOFFICE_KEY in the environment (it is never printed).", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(exist_ok=True)
    client = Client(key, args.order)
    report: list[str] = [f"Order: {args.order}"]

    print("Listing the latest run…")
    status, _, body = client.get("", "application/json")
    save("latest.json", client.scrub(body))
    if status != 200:
        report.append(f"Listing failed with {status}: {client.scrub(body)[:500]!r}")
        return finish(client, report)
    listing = json.loads(body)
    files = listing.get("orderDetails", {}).get("files", [])
    report.append(f"Top-level keys: {sorted(listing)}")
    report.append(f"orderDetails keys: {sorted(listing.get('orderDetails', {}))}")
    report.append(f"Files: {len(files)}")
    if files:
        report.append(f"File entry keys: {sorted(files[0])}")

    parsed: list[tuple[str, str, int, str]] = []
    for entry in files:
        file_id = entry.get("fileId", "")
        match = FILE_ID.match(file_id)
        if match:
            parsed.append((file_id, match["parameter"], int(match["step"]), match["run"]))
        note = "" if match else "   (does not match <param>_ts<step>_<run>)"
        report.append(f"  {file_id}{note}")
    params = sorted({p for _, p, _, _ in parsed})
    runs = sorted({r for _, _, _, r in parsed})
    report.append(f"Parameters: {params}")
    report.append(f"Run times (UTC, YYYYMMDDHH): {runs}")
    for param in params:
        steps = sorted(s for _, p, s, _ in parsed if p == param)
        report.append(f"  steps for {param}: {steps}")

    precip = args.file or next(
        (
            fid
            for fid, p, s, _ in sorted(parsed, key=lambda t: t[2])
            if s >= 1 and ("precip" in p.lower() or "rain" in p.lower())
        ),
        None,
    )
    land = next((e.get("fileId") for e in files if "land" in e.get("fileId", "").lower()), None)
    samples = [("precipitation", precip), ("land cover", land)]

    for label, file_id in samples:
        report.append("")
        if not file_id:
            report.append(f"No {label} file found in the listing.")
            continue
        report.append(f"{label}: {file_id}")
        print(f"Fetching {label} metadata and data…")
        status, _, body = client.get(file_path(file_id), "application/json")
        save(f"{file_id}.meta.json", client.scrub(body))
        report.append(f"  metadata status {status}")
        if status == 200:
            try:
                report += interesting_fields(json.loads(body))
            except json.JSONDecodeError:
                report.append(f"  metadata is not JSON: {body[:300]!r}")
        status, headers, body = client.get(file_path(file_id) + "/data", "application/octet-stream")
        report.append(f"  data status {status}, content-type {headers.get('Content-Type')}")
        if status == 200:
            save(f"{file_id}.png", body)
            report += describe_image(body)
        else:
            save(f"{file_id}.error.txt", client.scrub(body))
            report.append(f"  error body: {client.scrub(body)[:500]!r}")

    return finish(client, report)


def finish(client: Client, report: list[str]) -> int:
    report.append("")
    report.append(f"Calls made: {client.calls} (limit {MAX_CALLS})")
    (OUT_DIR / "calls.json").write_text(json.dumps(client.log, indent=2))
    text = "\n".join(report)
    (OUT_DIR / "report.txt").write_text(text + "\n")
    print()
    print(text)
    print(f"\nSaved to {OUT_DIR}/ (git-ignored).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
