import os
import json
import shutil
import hashlib
from pathlib import Path

from block_data   import BlockData
from coordinate   import Coordinate
from data_manager import DataManager

# ── Constants ──────────────────────────────────────────────────────
M                 = 2**32
A                 = 0x9E3779B9
SPACE_SIZE        = 60**6  # 6D coordinate space

# ── Paths for persistence ─────────────────────────────────────────
BASE_DIR          = Path(__file__).resolve().parent
COORD_DATA_DIR    = BASE_DIR / "coordinate_data"
STATE_DIR         = COORD_DATA_DIR
INDEX_PATH        = STATE_DIR / "conversation_index.json"
CURRENT_PATH      = STATE_DIR / "current_coord.json"  # UI only now

# ── Simple terminal progress bar ──────────────────────────────────
def print_progress(current: int, total: int, prefix: str = "") -> None:
    """
    Simple terminal progress bar: prefix [##########------] current/total
    """
    if total <= 0:
        return
    bar_len = 30
    ratio = current / total
    if ratio < 0:
        ratio = 0
    if ratio > 1:
        ratio = 1
    filled = int(bar_len * ratio)
    bar = "#" * filled + "-" * (bar_len - filled)
    print(f"\r{prefix} [{bar}] {current}/{total}", end="", flush=True)

# ── Deterministic start helper ────────────────────────────────────
def deterministic_start_for(key: str, salt: str = "v1") -> str:
    """
    Map a stable key (prefer conv_id) to a 6D base-60 coordinate string
    'c6 c5 c4 c3 c2 c1', uniformly over the 60^6 space.
    """
    if not key or not isinstance(key, str):
        raise ValueError("deterministic_start_for: key must be a non-empty string")

    h = hashlib.blake2b((salt + "|" + key).encode("utf-8"), digest_size=8).digest()
    n = int.from_bytes(h, "big") % SPACE_SIZE

    coord_inst = Coordinate()
    coord_str = coord_inst.strCoord_conv(n)  # uses same base-60 scheme as rest of system
    return coord_str

# ── Persistence Utilities (index + current coord) ─────────────────
def load_index():
    if not INDEX_PATH.exists():
        return {}
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("⚠ conversation_index.json corrupted; starting with empty index.")
            return {}

    # Shape guards & backward compatibility:
    for k, v in list(data.items()):
        if not isinstance(v, dict):
            del data[k]
            continue
        if "id" not in v:
            del data[k]
            continue
        # New field: count (blocks written so far)
        try:
            v["count"] = int(v.get("count", 0))
            if v["count"] < 0:
                v["count"] = 0
        except Exception:
            v["count"] = 0
        # Keep "start" if valid; we recompute anyway, but this is helpful for audit
        s = v.get("start")
        if isinstance(s, str):
            parts = s.split()
            if len(parts) != 6 or not all(p.isdigit() and 0 <= int(p) < 60 for p in parts):
                v.pop("start", None)
    return data

def save_index(index):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = INDEX_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    os.replace(tmp_path, INDEX_PATH)

def load_current_coord():
    """
    Kept for *display only*; no longer used to seed convo starts.
    """
    if not CURRENT_PATH.exists():
        return "0 0 0 0 0 0"
    with open(CURRENT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("current", "0 0 0 0 0 0")

def save_current_coord(coord):
    """
    Kept for UI display / curiosity; does not affect mapping logic.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CURRENT_PATH, "w", encoding="utf-8") as f:
        json.dump({"current": coord}, f)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# ── Default Navigation Path (unchanged math) ───────────────────────
class DefaultPath:
    def __init__(self, start_coord, key):
        if isinstance(start_coord, str):
            self.start_list = Coordinate.parse_coordinate(start_coord)
        else:
            self.start_list = start_coord
        self.coord_dec = Coordinate().baseTenConv(self.start_list)
        self.key       = key
        self.imag      = self.seed_imag(self.start_list, key)
        self.X         = self.seed_X(self.coord_dec, key)

    def seed_imag(self, coord_list, key):
        start_str = Coordinate().strCoord_conv(self.coord_dec)
        h = hashlib.blake2b((start_str + "|" + key).encode(), digest_size=8).digest()
        return int.from_bytes(h, "big") % M

    def seed_X(self, coord_dec, key):
        s = f"{coord_dec}|{key}".encode()
        h = hashlib.blake2b(s, digest_size=8).digest()
        return int.from_bytes(h, "big") % SPACE_SIZE

    def coord_const(self, c):
        return ((c[0]*13 + c[1]*17 + c[2]*19 + c[3]*23 + c[4]*29 + c[5]*31) & 0xFFFFFFFF)

    def imag_step(self, prev, curr, imag):
        mix = imag ^ self.coord_const(prev) ^ self.coord_const(curr)
        return (mix * A + 1) & 0xFFFFFFFF

    def real_step(self, real, imag):
        return (real*real - imag*imag + self.X) % SPACE_SIZE

    def step(self):
        coord_inst = Coordinate()
        prev       = coord_inst.coord_conv(self.coord_dec)
        self.coord_dec = self.real_step(self.coord_dec, self.imag)
        curr           = coord_inst.coord_conv(self.coord_dec)
        coord_inst.coordinates = curr
        self.imag = self.imag_step(prev, curr, self.imag)
        return coord_inst.get_coordinates()

# ── Utility: coordinate validation ─────────────────────────────────
def _validate_coord_str(coord: str) -> None:
    parts = coord.split()
    if len(parts) != 6 or not all(p.isdigit() and 0 <= int(p) < 60 for p in parts):
        raise ValueError(f"Invalid coordinate string: '{coord}' (must be 6 ints in [0..59]).")

# ── Mode 1: Store a single convo directory ────────────────────────
def store_conversation():
    index = load_index()
    print(f"(Global current for display only: {load_current_coord()})")

    print("Select source:")
    print(" 1) Sorted_GPT_Data")
    print(" 2) delta/new_chats")
    print(" 3) delta/appending")
    choice = input("Choice (1/2/3): ").strip()
    if choice == "1":
        base_dir = BASE_DIR / "Sorted_GPT_Data"
    elif choice == "2":
        base_dir = BASE_DIR / "delta" / "new_chats"
    elif choice == "3":
        base_dir = BASE_DIR / "delta" / "appending"
    else:
        print("Invalid choice.")
        return

    subs = [p for p in base_dir.iterdir() if p.is_dir()]
    if not subs:
        print(f"No conversations found in {base_dir}.")
        return

    print("\nAvailable conversations:")
    for p in subs:
        print(f" - {p.name}")
    user_input = input("\nEnter partial title or ID to store: ").strip().lower()
    matches = [p for p in subs if user_input in p.name.lower()]
    if not matches:
        print("❌ No matching conversation found.")
        return
    if len(matches) > 1:
        print("⚠️ Multiple matches found:")
        for i, p in enumerate(matches):
            print(f"  [{i}] {p.name}")
        idx = input("Enter index: ").strip()
        if not idx.isdigit() or int(idx) >= len(matches):
            print("❌ Invalid selection.")
            return
        convo_dir = matches[int(idx)]
    else:
        convo_dir = matches[0]
        confirm = input(f"\nSave conversation '{convo_dir.name}'? (y/n): ").strip().lower()
        if confirm != 'y':
            print("❌ Cancelled.")
            return

    json_files = list(convo_dir.glob("*.json"))
    if not json_files:
        print("❌ No JSON found.")
        return
    with open(json_files[0], encoding="utf-8") as f:
        convo = json.load(f)

    conv_id  = convo.get("id")
    messages = convo.get("messages", [])
    attachments = convo.get("attachments", [])

    # Use folder name as stable key (title_id)
    title_key = convo_dir.name

    # Deterministic start from conv_id
    start_str = deterministic_start_for(conv_id, salt="v1")
    _validate_coord_str(start_str)

    # Initialize / reconcile index entry
    entry = index.get(title_key)
    if entry is None:
        entry = {
            "id":   conv_id,
            "salt": "v1",
            "start": start_str,
            "count": 0,
        }
        index[title_key] = entry
    else:
        # sanity checks
        if entry.get("id") != conv_id:
            print(f"❌ ID mismatch for {title_key}: index={entry.get('id')} vs data={conv_id}")
            return
        if entry.get("salt", "v1") != "v1":
            print(f"❌ Salt mismatch for {title_key}: index={entry.get('salt')}")
            return
        # recompute start and warn if different
        if "start" in entry and entry["start"] != start_str:
            print(f"⚠ start mismatch for {title_key}: index={entry['start']} vs recomputed={start_str}")
        entry.setdefault("start", start_str)
        entry.setdefault("count", 0)

    already = entry["count"]
    # Build path from deterministic start
    nav = DefaultPath(start_coord=start_str, key=conv_id)
    current_coord = start_str

    # Skip already-written blocks to resume safely
    for _ in range(already):
        current_coord = nav.step()

    # Prepare DataManager for this convo
    dm = DataManager(base_dir=str(COORD_DATA_DIR), attachments_source_dir=str(convo_dir))

    # Store blocks along the path (pair user/bot)
    pairs = []
    for i in range(0, len(messages), 2):
        user_msg = messages[i].get("content","")
        bot_msg  = messages[i+1].get("content","") if i+1 < len(messages) else ""
        used = [a for a in attachments if a in user_msg or a in bot_msg]
        pairs.append((user_msg, bot_msg, used))

    total_pairs = len(pairs)
    total_blocks_written = 0

    for idx_block in range(already, total_pairs):
        user_msg, bot_msg, used = pairs[idx_block]
        block = BlockData(
            block={"user": user_msg, "assistant": bot_msg},
            universe=nav.imag,
            attachments=used
        )
        _validate_coord_str(current_coord)
        dm.create_coordinate_block(current_coord, block)
        total_blocks_written += 1

        current_coord = nav.step()
        save_current_coord(current_coord)  # UI only

        entry["count"] = idx_block + 1
        index[title_key] = entry
        sorted_index = dict(sorted(index.items(), key=lambda x: x[0].lower()))
        save_index(sorted_index)

        # Per-convo progress bar for this single store
        print_progress(idx_block + 1, total_pairs, prefix=f"{title_key[:20]}")

    if total_pairs:
        print()  # newline after progress bar

    # Cleanup delta if used
    if choice in ("2", "3"):
        shutil.rmtree(convo_dir)

    print(f"✅ Stored {total_blocks_written} NEW blocks for '{title_key}' from deterministic start {start_str}.")

# ── Mode 2: Restoration Logic ─────────────────────────────────────
def restore_conversation():
    index = load_index()
    if not index:
        print("❌ No conversations indexed yet.")
        return

    print("\nIndexed conversations:")
    for title_key, e in index.items():
        print(f" - {title_key} ({e['id']})  count={e.get('count',0)}")

    inp = input("\nEnter partial title or ID to restore: ").strip().lower()
    matches = [
        t for t, e in index.items()
        if inp in t.lower() or inp in str(e.get('id',"")).lower()
    ]
    if not matches:
        print("❌ No matching conversation.")
        return
    if len(matches) > 1:
        print("⚠️ Multiple matches:")
        for i, t in enumerate(matches):
            print(f"  [{i}] {t} ({index[t]['id']})")
        idx = input("Enter index: ").strip()
        if not idx.isdigit() or int(idx) >= len(matches):
            print("❌ Invalid.")
            return
        title_key = matches[int(idx)]
    else:
        title_key = matches[0]
        if input(f"\nRestore '{title_key}'? (y/n): ").strip().lower() != 'y':
            print("❌ Cancelled.")
            return

    meta    = index[title_key]
    conv_id = meta['id']
    start_str = meta.get('start') or deterministic_start_for(conv_id, salt="v1")
    _validate_coord_str(start_str)

    print(f"\nRestoring '{title_key}' ({conv_id}) from {start_str}")
    mode = input("View all (a) or step (s)? ").strip().lower() or 'a'

    dm   = DataManager(base_dir=str(COORD_DATA_DIR))
    path = DefaultPath(start_coord=start_str, key=conv_id)
    coord, imag = start_str, path.imag

    blocks = []
    while True:
        blkset = dm.load_coordinate_data(coord)
        b = next((b for b in blkset if b.get('universe') == imag), None)
        if not b:
            break
        blocks.append((coord, imag, b))
        coord = path.step()
        imag = path.imag

    if not blocks:
        print("❌ No blocks.")
        return

    def print_blk(i, c, u, bl):
        print("\n" + "─" * 40)
        print(f"Block {i+1}/{len(blocks)} @ {c} | universe {u}")
        print("User:     ", bl['block'].get('user', ''))
        print("Assistant:", bl['block'].get('assistant', ''))
        if bl.get('attachments'):
            print("Attachments:")
            for a in bl['attachments']:
                print(f"  - {a}")
        print("─" * 40)

    if mode == 'a':
        for i, (c, u, bl) in enumerate(blocks):
            print_blk(i, c, u, bl)
        print("\n✅ Restoration complete.")
    else:
        idx = 0
        while 0 <= idx < len(blocks):
            clear_screen()
            c, u, bl = blocks[idx]
            print_blk(idx, c, u, bl)
            next_line = f" | next: {blocks[idx+1][0]}" if idx + 1 < len(blocks) else ""
            print(f"[end of block {idx+1}/{len(blocks)} @ {c} | universe {u}{next_line}]")
            cmd = input("Press [Enter] for next, 'b' for back, or 'q' to quit: ").strip().lower()

            if cmd in ("", "n", "next"):
                idx += 1
            elif cmd in ("b", "back"):
                if idx > 0:
                    idx -= 1
                else:
                    print("↩️ Already at the first block.")
                    input("Press Enter to continue...")
            elif cmd in ("q", "quit"):
                break
            else:
                print("❓ Unknown command. Use Enter / b / q.")
                input("Press Enter to continue...")

        print("\n✅ Restoration ended.")

# ── Mode 3: Recursively store ALL GPTSorted/delta convos ──────────
def store_all_conversations():
    index = load_index()
    print(f"(Global current for display only: {load_current_coord()})")
    print("Select batch source:")
    print(" 1) Sorted_GPT_Data *recommended if first time storing")
    print(" 2) delta folder (new_chats then appending) *recommended if not first time")
    choice = input("Choice (1/2): ").strip()

    def process_folder(convo_dir):
        nonlocal index

        title_key = convo_dir.name
        jf = list(convo_dir.glob("*.json"))
        if not jf:
            print(f"\n❌ No JSON in {title_key}")
            return

        convo = json.loads(jf[0].read_text(encoding="utf-8"))
        conv_id = convo.get("id")
        msgs    = convo.get("messages", [])
        atts    = convo.get("attachments", [])

        # Deterministic start
        start_str = deterministic_start_for(conv_id, salt="v1")
        _validate_coord_str(start_str)

        entry = index.get(title_key)
        if entry is None:
            entry = {"id": conv_id, "salt": "v1", "start": start_str, "count": 0}
            index[title_key] = entry
        else:
            if entry.get("id") != conv_id:
                print(f"\n❌ ID mismatch for '{title_key}' in batch.")
                return
            if entry.get("salt", "v1") != "v1":
                print(f"\n❌ Salt mismatch for '{title_key}' in batch.")
                return
            if "start" in entry and entry["start"] != start_str:
                print(f"\n⚠ start mismatch for '{title_key}' in batch: idx={entry['start']} vs {start_str}")
            entry.setdefault("start", start_str)
            entry.setdefault("count", 0)

        already = entry["count"]
        nav = DefaultPath(start_coord=start_str, key=conv_id)
        current_coord = start_str

        # Fast-forward to current count
        for _ in range(already):
            current_coord = nav.step()

        dm = DataManager(base_dir=str(COORD_DATA_DIR), attachments_source_dir=str(convo_dir))

        pairs = []
        for i in range(0, len(msgs), 2):
            user_msg = msgs[i].get("content", "")
            bot_msg  = msgs[i+1].get("content", "") if i+1 < len(msgs) else ""
            used = [a for a in atts if a in user_msg or a in bot_msg]
            pairs.append((user_msg, bot_msg, used))

        total_pairs = len(pairs)

        for idx_block in range(already, total_pairs):
            user_msg, bot_msg, used = pairs[idx_block]
            block = BlockData(
                block={"user": user_msg, "assistant": bot_msg},
                universe=nav.imag,
                attachments=used
            )
            _validate_coord_str(current_coord)
            dm.create_coordinate_block(current_coord, block)

            current_coord = nav.step()
            save_current_coord(current_coord)

            entry["count"] = idx_block + 1
            index[title_key] = entry
            sorted_idx = dict(sorted(index.items(), key=lambda x: x[0].lower()))
            save_index(sorted_idx)

        # done with this convo
        return

    if choice == "1":
        root = BASE_DIR / "Sorted_GPT_Data"
        convo_dirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
        total = len(convo_dirs)
        for i, convo_dir in enumerate(convo_dirs, start=1):
            print_progress(i, total, prefix="Conversations")
            process_folder(convo_dir)
        if total:
            print()
    elif choice == "2":
        # new chats
        new_root = BASE_DIR / "delta" / "new_chats"
        new_dirs = [d for d in sorted(new_root.iterdir()) if d.is_dir()]
        total_new = len(new_dirs)
        for i, convo_dir in enumerate(new_dirs, start=1):
            print_progress(i, total_new, prefix="New chats")
            process_folder(convo_dir)
            shutil.rmtree(convo_dir)
        if total_new:
            print()

        # appending
        app_root = BASE_DIR / "delta" / "appending"
        app_dirs = [d for d in sorted(app_root.iterdir()) if d.is_dir()]
        total_app = len(app_dirs)
        for i, convo_dir in enumerate(app_dirs, start=1):
            print_progress(i, total_app, prefix="Appending")
            process_folder(convo_dir)
            shutil.rmtree(convo_dir)
        if total_app:
            print()
    else:
        print("Invalid choice.")
        return

    print("\n🎉 Batch import complete.")

# ── Main Menu ───────────────────────────────────────────────────────
def main():
    print("=== NavigationHub + DataManager ===")
    print("1) store one   — import a single convo directory")
    print("2) restore     — replay a stored convo")
    print("3) recurse     — import all GPTSorted / delta subfolders")
    print("4) browse      — interactive explore")
    choice = input("Select mode (1-4):").strip()
    if choice == '1':
        store_conversation()
    elif choice == '2':
        restore_conversation()
    elif choice == '3':
        store_all_conversations()
    elif choice == '4':
        print("Interactive browsing no longer supported.")
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
