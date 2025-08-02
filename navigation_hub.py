import os
import re
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
CURRENT_PATH      = STATE_DIR / "current_coord.json"

# ── Persistence Utilities ─────────────────────────────────────────
def load_index():
    if not INDEX_PATH.exists():
        return {}
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_index(index):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

def load_current_coord():
    if not CURRENT_PATH.exists():
        return "0 0 0 0 0 0"
    with open(CURRENT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("current", "0 0 0 0 0 0")

def save_current_coord(coord):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CURRENT_PATH, "w", encoding="utf-8") as f:
        json.dump({"current": coord}, f)

# ── Default Navigation Path ────────────────────────────────────────
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

# ── Utility: retrace to known end coordinate ────────────────────────
def retrace_to_end(start_str, end_str, key):
    """
    Walks the DefaultPath from start_str until end_str, returning
    (coord, imag, DefaultPath) at that final point.
    """
    path = DefaultPath(start_coord=start_str, key=key)
    coord = start_str
    imag = path.imag
    # iterate until we reach the stored end coordinate
    while coord != end_str:
        coord = path.step()
        imag = path.imag
    return coord, imag, path

# ── Mode 1: Store a single convo directory ───────────────────────────
def store_conversation():
    index = load_index()
    current_coord_str = load_current_coord()
    print(f"Starting from current coordinate: {current_coord_str}")

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
        for i, p in enumerate(matches): print(f"  [{i}] {p.name}")
        idx = input("Enter index: ").strip()
        if not idx.isdigit() or int(idx) >= len(matches): print("❌ Invalid selection."); return
        convo_dir = matches[int(idx)]
    else:
        convo_dir = matches[0]
        confirm = input(f"\nSave conversation '{convo_dir.name}'? (y/n): ").strip().lower()
        if confirm != 'y': print("❌ Cancelled."); return

    json_files = list(convo_dir.glob("*.json"))
    if not json_files:
        print("❌ No JSON found."); return
    with open(json_files[0], encoding="utf-8") as f:
        convo = json.load(f)

    title = convo.get("title","untitled")
    conv_id = convo.get("id")
    messages = convo.get("messages", [])
    attachments = convo.get("attachments", [])

    # ── Handle appending vs new ───────────────────────────────────────
    if choice == "3":
        # append: retrace to the existing end coordinate
        meta = index.get(title)
        if not meta or meta.get("id") != conv_id:
            print("❌ Conversation not indexed; cannot append.")
            return
        start_str = meta["start"]
        end_str = meta["end"]
        coord, imag, nav = retrace_to_end(start_str, end_str, conv_id)
        current_coord = coord
        print(f"Appending to '{title}' from {current_coord} (imag: {imag})")
    else:
        # new: start from global current
        nav = DefaultPath(start_coord=current_coord_str, key=conv_id)
        current_coord = current_coord_str
        start_str = current_coord

    dm = DataManager(base_dir=str(COORD_DATA_DIR), attachments_source_dir=str(convo_dir))

    # ── Store blocks along the path ────────────────────────────────────
    total_blocks = 0
    for i in range(0, len(messages), 2):
        user_msg = messages[i].get("content","")
        bot_msg = messages[i+1].get("content","") if i+1<len(messages) else ""
        used = [a for a in attachments if a in user_msg or a in bot_msg]
        block = BlockData(block={"user":user_msg,"assistant":bot_msg}, universe=nav.imag, attachments=used)
        dm.create_coordinate_block(current_coord, block)
        total_blocks += 1

        # advance
        current_coord = nav.step()
        save_current_coord(current_coord)

    end_str = current_coord

    # ── Update conversation index ──────────────────────────────────────
    index[title] = {"id": conv_id, "start": start_str, "end": end_str}
    sorted_index = dict(sorted(index.items(), key=lambda x: x[0].lower()))
    save_index(sorted_index)

    # ── Cleanup delta if used ─────────────────────────────────────────
    if choice in ("2","3"):
        shutil.rmtree(convo_dir)

    print(f"✅ Stored {total_blocks} blocks for '{title}' from {start_str} → {end_str}.")

# ── Mode 2: Restoration Logic ──────────────────────────────────────────────
def restore_conversation():
    index = load_index()
    if not index:
        print("❌ No conversations indexed yet."); return
    print("\nIndexed conversations:")
    for title, e in index.items(): print(f" - {title} ({e['id']})")
    inp = input("\nEnter partial title or ID to restore: ").strip().lower()
    matches = [t for t,e in index.items() if inp in t.lower() or inp in e['id'].lower()]
    if not matches:
        print("❌ No matching conversation."); return
    if len(matches)>1:
        print("⚠️ Multiple matches:")
        for i,t in enumerate(matches): print(f"  [{i}] {t} ({index[t]['id']})")
        idx = input("Enter index: ").strip()
        if not idx.isdigit() or int(idx)>=len(matches): print("❌ Invalid."); return
        title = matches[int(idx)]
    else:
        title = matches[0]
        if input(f"\nRestore '{title}'? (y/n): ").strip().lower()!='y': print("❌ Cancelled."); return
    meta = index[title]
    conv_id, start_str = meta['id'], meta['start']
    print(f"\nRestoring '{title}' ({conv_id}) from {start_str} → {meta['end']}")
    mode = input("View all (a) or step (s)? ").strip().lower() or 'a'
    dm = DataManager(base_dir=str(COORD_DATA_DIR))
    path = DefaultPath(start_coord=start_str, key=conv_id)
    coord, imag = start_str, path.imag
    blocks=[]
    while True:
        blkset=dm.load_coordinate_data(coord)
        b=next((b for b in blkset if b.get('universe')==imag),None)
        if not b: break
        blocks.append((coord,imag,b))
        coord = path.step()
        imag = path.imag
    if not blocks: print("❌ No blocks."); return
    def print_blk(i,c,u,bl):
        print("\n"+"─"*40)
        print(f"Block {i+1}/{len(blocks)} @ {c} | universe {u}")
        print("User:     ",bl['block'].get('user',''))
        print("Assistant:",bl['block'].get('assistant',''))
        if bl.get('attachments'):
            print("Attachments:")
            for a in bl['attachments']: print(f"  - {a}")
        print("─"*40)
    if mode=='a':
        for i,(c,u,bl) in enumerate(blocks): print_blk(i,c,u,bl)
        print("\n✅ Restoration complete.")
    else:
        idx=0
        while idx<len(blocks):
            print_blk(idx,*blocks[idx])
            if input("Enter next or 'q' to quit: ").strip().lower()=='q': break
            idx+=1
        print("\n✅ Restoration ended.")

# ── Mode 3: Recursively store ALL GPTSorted convos ───────────────────
def store_all_conversations():
    index = load_index()
    current = load_current_coord()
    print(f"Resuming from {current}")
    print("Select batch source:")
    print(" 1) Sorted_GPT_Data")
    print(" 2) delta folder (new_chats then appending)")
    choice = input("Choice (1/2): ").strip()

    # helper to process a single folder
    def process_folder(convo_dir, append=False):
        title = convo_dir.name
        # skip new if exists
        if not append and title in index:
            print(f"⚠️ Skipping '{title}' — already indexed.")
            return
        # skip append if missing
        if append and title not in index:
            print(f"⚠️ Skipping '{title}' — no base convo to append.")
            return
        # load JSON
        jf = list(convo_dir.glob("*.json"))
        if not jf:
            print(f"❌ No JSON in {title}")
            return
        convo = json.loads(jf[0].read_text(encoding="utf-8"))
        conv_id = convo.get("id")
        msgs = convo.get("messages", [])
        atts = convo.get("attachments", [])

        # determine start coord and nav state
        if append:
            meta = index[title]
            start_str = meta["start"]
            end_str = meta["end"]
            coord, imag, nav = retrace_to_end(start_str, end_str, conv_id)
            print(f"Appending '{title}' from {coord} (imag={imag})")
            current_coord = coord
        else:
            nav = DefaultPath(start_coord=current, key=conv_id)
            current_coord = current
            index[title] = {"id": conv_id, "start": current_coord, "end": current_coord}
            print(f"Storing new '{title}' starting at {current_coord}")

        # store blocks
        dm = DataManager(base_dir=str(COORD_DATA_DIR), attachments_source_dir=str(convo_dir))
        for i in range(0, len(msgs), 2):
            user_msg = msgs[i].get("content", "")
            bot_msg = msgs[i+1].get("content", "") if i+1 < len(msgs) else ""
            used = [a for a in atts if a in user_msg or a in bot_msg]
            block = BlockData(block={"user":user_msg,"assistant":bot_msg}, universe=nav.imag, attachments=used)
            dm.create_coordinate_block(current_coord, block)
            current_coord = nav.step()
            save_current_coord(current_coord)
        # update index end
        index[title]["end"] = current_coord
        # cleanup
        print(f"✅ {'Appended' if append else 'Stored'} '{title}' → {current_coord}")
        return current_coord

    # process sorted folder
    if choice == "1":
        root = BASE_DIR / "Sorted_GPT_Data"
        for convo_dir in sorted(root.iterdir()):
            if convo_dir.is_dir():
                current = process_folder(convo_dir, append=False)
    # process delta
    elif choice == "2":
        # new chats
        new_root = BASE_DIR / "delta" / "new_chats"
        for convo_dir in sorted(new_root.iterdir()):
            if convo_dir.is_dir():
                current = process_folder(convo_dir, append=False)
                shutil.rmtree(convo_dir)
        # appending
        app_root = BASE_DIR / "delta" / "appending"
        for convo_dir in sorted(app_root.iterdir()):
            if convo_dir.is_dir():
                current = process_folder(convo_dir, append=True)
                shutil.rmtree(convo_dir)
    else:
        print("Invalid choice.")
        return

    # save index and final coord
    sorted_idx = dict(sorted(index.items(), key=lambda x: x[0].lower()))
    save_index(sorted_idx)
    save_current_coord(current)
    print("\n🎉 Batch import complete.")

# ── Main Menu ───────────────────────────────────────────────────────
def main():
    print("=== NavigationHub + DataManager ===")
    print("1) store one   — import a single convo directory")
    print("2) restore     — replay a stored convo")
    print("3) recurse     — import all GPTSorted subfolders")
    print("4) browse      — interactive explore")
    choice=input("Select mode (1-4):").strip()
    if choice=='1': store_conversation()
    elif choice=='2': restore_conversation()
    elif choice=='3': store_all_conversations()
    elif choice=='4':
        print("Interactive browsing no longer supported.")
    else: print("Invalid choice.")

if __name__=="__main__": main()
