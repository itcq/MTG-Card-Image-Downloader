
----------------------
Paste or point to a text list of Magic: The Gathering card names and download images
from Scryfall to your local machine.

Features
- Reads from a file (--input path) or stdin (paste your list, hit Ctrl-D / Ctrl-Z+Enter on Windows).
- Understands common decklist formats, like:
    3 Lightning Bolt
    4x Counterspell
    1 Abrupt Decay (rvr) 125
    2 Boseiju, Who Endures (NEO)
    1 Jace, Vryn's Prodigy // Jace, Telepath Unbound (ORI) 60
    1 Forest
- Batches lookups using the /cards/collection endpoint (75 identifiers per request).
- Handles double-faced cards and downloads each face.
- Selectable image size: png|large|normal|small|art_crop|border_crop (default: png).
- Optional per-set subfolders, quantity-aware filenames, and overwrite behavior.

Usage examples
--------------
# Read from a file and save PNGs into "./cards"
python scryfall_downloader.py --input decklist.txt --out cards --size png

# Paste from clipboard/terminal (stdin), save large JPGs (Scryfall's "large")
cat decklist.txt | python scryfall_downloader.py --out images --size large

# Organize by set subfolders and ignore quantities (one image per unique printing)
python scryfall_downloader.py --input decklist.txt --by-set --unique

# On Windows PowerShell, paste then press Ctrl+Z then Enter to end stdin.
python .\scryfall_downloader.py --size normal --out .\images

# Save images under a folder named after the deck list text file.
If you provide --input FILE and do NOT provide --out, this script will automatically 
create/use an output folder named after FILE's base name (without extension).

Example:
  decklists.py --input "Jund Midrange.txt"
  -> images go into ./Jund Midrange

If you paste from stdin and omit --out, it falls back to ./cards.

Requirements
------------
- Python 3.8+
- pip install requests tqdm

Notes
-----
- Scryfall API docs: https://scryfall.com/docs/api
- This script respects Scryfall's recommended batching. Please avoid excessive parallelism.
"""
