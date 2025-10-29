#!/usr/bin/env python3
r"""
scryfall_downloader_named_output.py
-----------------------------------
Like scryfall_downloader_debug.py, but if you provide --input FILE and do NOT
provide --out, this script will automatically create/use an output folder named
after FILE's base name (without extension).

Example:
  python scryfall_downloader_named_output.py --input "Jund Midrange.txt"
  -> images go into ./Jund Midrange

If you paste from stdin and omit --out, it falls back to ./cards.
"""

import argparse
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests
from tqdm import tqdm

SCRYFALL_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
BATCH_SIZE = 75
VALID_SIZES = {"png", "large", "normal", "small", "art_crop", "border_crop"}


def dprint(debug: bool, *args):
    if debug:
        print("[DEBUG]", *args, file=sys.stderr)


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^\w\s\-\(\)\[\]\.&,'!+]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name)
    return name


def parse_deck_line(line: str) -> Optional[Dict]:
    s = line.strip()
    if not s:
        return None
    if s.startswith(("#", "//", "Sideboard", "Commander", "Companion", "Maybeboard")):
        return None
    s = re.sub(r"\*F\*|\(Foil\)", "", s, flags=re.IGNORECASE).strip()

    m_qty = re.match(r"^(\d+)\s*x?\s+(.*)$", s, flags=re.IGNORECASE)
    if m_qty:
        qty = int(m_qty.group(1))
        rest = m_qty.group(2).strip()
    else:
        qty = 1
        rest = s

    m_set = re.search(r"\(([A-Za-z0-9]{2,5})\)", rest)
    set_code = m_set.group(1).lower() if m_set else None
    if m_set:
        rest_wo_set = (rest[:m_set.start()] + rest[m_set.end():]).strip()
    else:
        rest_wo_set = rest

    m_num = re.search(r"\b(\d+[a-z]?)\b\s*$", rest_wo_set, flags=re.IGNORECASE)
    if m_num:
        collector_number = m_num.group(1)
        name = rest_wo_set[: m_num.start()].strip()
    else:
        collector_number = None
        name = rest_wo_set.strip()

    name = re.sub(r"\s*//\s*", " // ", name)
    if not name:
        return None

    return {"qty": qty, "name": name, "set": set_code, "collector_number": collector_number}


def read_decklist_from_stdin() -> List[str]:
    if sys.stdin.isatty():
        print(
            "Paste your decklist, then press Ctrl-D (macOS/Linux) or Ctrl-Z then Enter (Windows) to finish input:\n",
            file=sys.stderr,
        )
    data = sys.stdin.read()
    if not data.strip():
        print("No input detected on stdin. Did you press Ctrl-Z then Enter on Windows? "
              "Tip: Use --input decklist.txt to avoid stdin.", file=sys.stderr)
    return [line for line in data.splitlines()]


def read_decklist_from_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    if not txt.strip():
        print(f"Input file is empty: {path}", file=sys.stderr)
    return [line for line in txt.splitlines()]


def build_identifiers(entries: List[Dict]) -> List[Dict]:
    identifiers = []
    for e in entries:
        if e.get("set") and e.get("collector_number"):
            identifiers.append({"set": e["set"], "collector_number": str(e["collector_number"])})
        elif e.get("set"):
            identifiers.append({"name": e["name"], "set": e["set"]})
        else:
            identifiers.append({"name": e["name"]})
    return identifiers


def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def pick_image_uris(card: Dict, size: str):
    uris = []
    if "image_uris" in card and card["image_uris"]:
        iu = card["image_uris"]
        if size not in iu:
            raise KeyError(f"No '{size}' image for {card.get('name')}")
        uris.append((iu[size], ""))
    elif "card_faces" in card and card["card_faces"]:
        faces = card["card_faces"]
        for idx, face in enumerate(faces):
            if "image_uris" not in face or size not in face["image_uris"]:
                raise KeyError(f"No '{size}' image for face {idx+1} of {card.get('name')}")
            face_name = face.get("name", f"face{idx+1}")
            suffix = f"-{sanitize_filename(face_name)}"
            uris.append((face["image_uris"][size], suffix))
    else:
        raise KeyError(f"No image_uris found for {card.get('name')}")
    return uris


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def download_file(session: requests.Session, url: str, dest: str, overwrite: bool = False, delay: float = 0.0):
    if not overwrite and os.path.exists(dest):
        return
    with session.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    if delay > 0:
        time.sleep(delay)


def make_filename(card: Dict, qty: int, face_suffix: str) -> str:
    set_code = (card.get("set") or "").lower()
    cn = card.get("collector_number") or ""
    name = sanitize_filename(card.get("name", "Unknown"))
    qty_prefix = f"{qty}x " if qty > 1 else ""
    set_part = f" ({set_code})" if set_code else ""
    num_part = f" {cn}" if cn else ""
    base = f"{qty_prefix}{name}{face_suffix}{set_part}{num_part}"
    return base


def infer_extension_from_url(url: str) -> str:
    m = re.search(r"\.(png|jpg|jpeg)(?:\?|$)", url, flags=re.IGNORECASE)
    if m:
        return "." + m.group(1).lower()
    return ".img"


def group_by_identifier(entries: List[Dict]) -> Dict[str, List[Dict]]:
    def key(e):
        if e.get("set") and e.get("collector_number"):
            return f"set:{e['set']}#cn:{e['collector_number']}"
        elif e.get("set"):
            return f"name:{e['name'].lower()}#set:{e['set']}"
        else:
            return f"name:{e['name'].lower()}"
    groups = {}
    for e in entries:
        groups.setdefault(key(e), []).append(e)
    return groups


def main():
    parser = argparse.ArgumentParser(description="Download MTG card images from Scryfall (auto-named output folder).")
    parser.add_argument("--input", "-i", type=str, help="Path to decklist text file. If omitted, read from stdin.")
    parser.add_argument("--out", "-o", type=str, default=None, help="Output directory. If omitted and --input is provided, uses the input filename (no extension). Otherwise defaults to ./cards")
    parser.add_argument("--size", "-s", type=str, default="png", choices=sorted(VALID_SIZES), help="Image size (default: png)")
    parser.add_argument("--unique", action="store_true", help="Ignore quantities; one image per unique identifier")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay in seconds between file downloads (default: 0)")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds (default: 30)")
    parser.add_argument("--debug", action="store_true", help="Verbose debug logs to stderr")
    args = parser.parse_args()

    # Decide output directory based on input file name if --out not supplied
    if args.out is None:
        if args.input:
            base = os.path.splitext(os.path.basename(args.input))[0]
            out_dir = base
        else:
            out_dir = "cards"
    else:
        out_dir = args.out

    # Prepare input
    if args.input:
        lines = read_decklist_from_file(args.input)
    else:
        lines = read_decklist_from_stdin()

    # Parse
    parsed = []
    for line in lines:
        e = parse_deck_line(line)
        if e:
            parsed.append(e)

    if not parsed:
        print("No cards parsed from input. If you pasted on Windows, be sure to press Ctrl-Z then Enter. "
              "Or run with --input deckname.txt", file=sys.stderr)
        sys.exit(1)

    grouped = group_by_identifier(parsed)
    aggregated: List[Dict] = []
    for _k, items in grouped.items():
        total_qty = sum(i["qty"] for i in items)
        exemplar = items[0].copy()
        exemplar["qty"] = 1 if args.unique else total_qty
        aggregated.append(exemplar)

    identifiers = build_identifiers(aggregated)
    print(f"Output folder: {out_dir}", file=sys.stderr)
    print(f"Found {len(aggregated)} unique identifiers from {len(parsed)} lines.", file=sys.stderr)

    # HTTP session
    session = requests.Session()
    session.headers.update({"User-Agent": "scryfall-downloader/1.2 (+https://scryfall.com/docs/api)"})
    timeout = args.timeout

    # Resolve cards in batches
    resolved_cards: List[Tuple[Dict, int]] = []
    missing: List[Dict] = []

    for start in range(0, len(identifiers), BATCH_SIZE):
        batch_ids = identifiers[start:start+BATCH_SIZE]
        payload = {"identifiers": batch_ids}
        resp = session.post(SCRYFALL_COLLECTION_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        returned = data.get("data", [])
        for nf in data.get("not_found", []):
            missing.append(nf)
        for card_json, entry in zip(returned, aggregated[start:start+BATCH_SIZE]):
            resolved_cards.append((card_json, entry["qty"]))

    # Download
    ensure_dir(out_dir)
    errors = []
    pbar = tqdm(total=len(resolved_cards), desc="Downloading", unit="card")
    for card_json, qty in resolved_cards:
        try:
            pairs = pick_image_uris(card_json, size=args.size)
            for url, suffix in pairs:
                base = make_filename(card_json, qty=qty, face_suffix=suffix)
                ext = infer_extension_from_url(url)
                dest_path = os.path.join(out_dir, f"{base}{ext}")
                download_file(session, url, dest_path, overwrite=args.overwrite, delay=args.delay)
        except Exception as ex:
            name = card_json.get("name", "Unknown")
            errors.append((name, str(ex)))
        finally:
            pbar.update(1)
    pbar.close()

    if missing:
        print("\nNot found (check spelling/printing):", file=sys.stderr)
        for nf in missing:
            print(f"  - {nf}", file=sys.stderr)

    if errors:
        print("\nErrors while downloading:", file=sys.stderr)
        for nm, msg in errors:
            print(f"  - {nm}: {msg}", file=sys.stderr)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
