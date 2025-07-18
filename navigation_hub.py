import os
import json
import hashlib

from block_data    import BlockData
from coordinate    import Coordinate
from data_manager  import DataManager

# ── Constants ────────────────────────────────────────────────────────────────
M          = 2**32
A          = 0x9E3779B9
SPACE_SIZE = 60**6  # 6D coordinate space

# ── Default Navigation Function ─────────────────────────────────────────────
class DefaultPath:
    def __init__(self, start_coord, key):
        if isinstance(start_coord, str):
            self.start_list = Coordinate.parse_coordinate(start_coord)
        else:
            self.start_list = start_coord

        self.coord_dec = Coordinate().baseTenConv(self.start_list)
        self.key       = key
        self.imag      = self.seed_imag(self.start_list, key)

    def seed_imag(self, coord_list, key):
        start_str = Coordinate().strCoord_conv(self.coord_dec)
        h = hashlib.blake2b((start_str + "|" + key).encode(), digest_size=8).digest()
        return int.from_bytes(h, "big") % M

    def coord_const(self, c):
        return (
            (c[0]*13 + c[1]*17 + c[2]*19 +
             c[3]*23 + c[4]*29 + c[5]*31)
            & 0xFFFFFFFF
        )

    def imag_step(self, prev, curr, imag):
        mix = imag ^ self.coord_const(prev) ^ self.coord_const(curr)
        return (mix * A + 1) & 0xFFFFFFFF

    def real_step(self, real, imag):
        return (real*real - imag*imag) % SPACE_SIZE

    def step(self):
        coord_inst = Coordinate()
        prev       = coord_inst.coord_conv(self.coord_dec)

        self.coord_dec   = self.real_step(self.coord_dec, self.imag)
        curr            = coord_inst.coord_conv(self.coord_dec)
        coord_inst.coordinates = curr

        self.imag = self.imag_step(prev, curr, self.imag)
        return coord_inst.get_coordinates()

# ── NavigationHub CLI (optional) ────────────────────────────────────────────
class NavigationHub:
    def __init__(self, start_coord_str="00 00 00 00 00 00"):
        self.coord_obj = Coordinate()
        try:
            coord_list = self.coord_obj.parse_coordinate(start_coord_str)
        except ValueError:
            print("Invalid input. Defaulting to all zeros.")
            coord_list = [0]*6

        self.coord_obj.coordinates = coord_list
        self.start_coord = coord_list
        self.active_path = None
        self.commands    = {
            "help":    self.show_help,
            "default": self.default,
            "step":    self.step,
            "exit":    lambda: "exit",
        }

    def show_help(self):
        print("Available commands:")
        for c in self.commands:
            print(f"- {c}")

    def default(self, key=None, start=None):
        if key is None:
            key = input("Enter key: ").strip()

        # Determine start list (either passed-in string or previous start_coord)
        sc = start or self.start_coord
        if isinstance(sc, str):
            sc = self.coord_obj.parse_coordinate(sc)

        # ── NEW: update the hub's coordinate object to this start ──────────
        self.coord_obj.coordinates = sc

        # Seed your navigation path from that coordinate
        self.active_path = DefaultPath(sc, key)

        # Now get_coordinates() will reflect the correct start
        start_str = self.coord_obj.get_coordinates()
        print(f"Starting path at {start_str} | imag: {self.active_path.imag}")
        return start_str, self.active_path.imag

    def step(self):
        if not self.active_path:
            print("No active path. Run 'default' first.")
            return
        coord_str = self.active_path.step()
        print(f"Next coordinate: {coord_str} | imag: {self.active_path.imag}")
        return coord_str, self.active_path.imag

    def run(self):
        print("NavigationHub: type 'help' for commands.")
        while True:
            cmd = input("Nav> ").strip().lower()
            if not cmd:
                continue
            if cmd not in self.commands:
                print("Unknown command. Type 'help'.")
                continue
            res = self.commands[cmd]()
            if res == "exit":
                print("Exiting NavigationHub.")
                break

# ── Mode 1: Store a single convo directory ───────────────────────────────────
def store_conversation():
    convo_dir   = input("Path to your single conversation directory: ").strip()
    data_root   = input("Base data directory (default 'data'): ").strip() or "data"
    start_coord = input("Starting coordinate (6 nums; blank=all zeros): ").strip() \
                  or "00 00 00 00 00 00"
    key         = input("Enter key for navigation: ").strip()

    nav = NavigationHub(start_coord)
    nav.default(key=key)

    dm = DataManager(
        base_dir               = data_root,
        attachments_source_dir = convo_dir
    )

    json_files = [f for f in os.listdir(convo_dir) if f.endswith(".json")]
    if not json_files:
        print("❌ No .json file found.")
        return
    with open(os.path.join(convo_dir, json_files[0]), "r", encoding="utf-8") as f:
        convo = json.load(f)

    messages    = convo.get("messages", [])
    attachments = convo.get("attachments", [])

    coord_inst       = Coordinate()
    current_coord    = coord_inst.strCoord_conv(nav.active_path.coord_dec)
    current_universe = nav.active_path.imag
    total_blocks     = 0

    for i in range(0, len(messages), 2):
        user_msg = messages[i].get("content","")
        bot_msg  = messages[i+1].get("content","") if i+1 < len(messages) else ""

        used_atts = [
            att for att in attachments
            if att in user_msg or att in bot_msg
        ]

        block = BlockData(
            block       = {"user": user_msg, "assistant": bot_msg},
            universe    = current_universe,
            attachments = used_atts
        )

        dm.create_coordinate_block(current_coord, block)
        total_blocks += 1

        # step ahead
        current_coord    = nav.active_path.step()
        current_universe = nav.active_path.imag

    print(f"✅ Stored {total_blocks} blocks under '{data_root}'.")

# ── Mode 2: Restore a stored conversation ────────────────────────────────────
def restore_conversation():
    data_root   = input("Base data directory (default 'data'): ").strip() or "data"
    start_coord = input("Starting coordinate (6 nums; blank=all zeros): ").strip() \
                  or "00 00 00 00 00 00"
    key         = input("Enter key for navigation: ").strip()
    max_steps_s = input("Max steps (blank=until empty): ").strip()

    max_steps = int(max_steps_s) if max_steps_s.isdigit() else None

    nav = NavigationHub(start_coord)
    nav.default(key=key)

    dm = DataManager(base_dir=data_root)

    coord_inst    = Coordinate()
    current_coord = coord_inst.strCoord_conv(nav.active_path.coord_dec)
    steps         = 0

    while True:
        all_blocks = dm.load_coordinate_data(current_coord)
        if not all_blocks:
            if steps == 0:
                print("❌ No blocks found at starting coordinate.")
            break

        current_universe = nav.active_path.imag
        block = next(
            (b for b in all_blocks if b.get("universe")==current_universe),
            None
        )
        if block is None:
            print(f"⚠️ No block for universe {current_universe} at {current_coord}.")
            break

        print(f"\n▶ Coordinate {current_coord} | universe {current_universe}")
        user      = block["block"].get("user","")
        assistant = block["block"].get("assistant","")
        print(f"\nUser:      {user}")
        print(f"Assistant: {assistant}")

        atts = block.get("attachments", [])
        if atts:
            _, full_key, dir_path, _ = dm._paths(current_coord)
            att_base = os.path.join(dir_path, "attachments", full_key)
            print("Attachments:")
            for fn in atts:
                print("  " + os.path.join(att_base, fn))

        steps += 1
        if max_steps and steps >= max_steps:
            break

        current_coord = nav.active_path.step()

    print("\n✅ Restoration complete.")

# ── Mode 3: Recursively store ALL GPTSorted convos ──────────────────────────
def store_all_conversations():
    gpts_root = input("Path to GPTSorted root directory (default 'GPTSorted'): ").strip() or "GPTSorted"
    data_root = input("Base data directory (default 'data'): ").strip() or "data"

    # ── Step 1: Prepare index list ─────────────────────────────────────────
    index_mapping: list[tuple[str, str]] = []

    # Initialize at all-zero coordinate
    init_coord = "00 00 00 00 00 00"
    nav = NavigationHub(init_coord)
    current_coord_str = init_coord

    dm = DataManager(base_dir=data_root)

    for convo_name in sorted(os.listdir(gpts_root)):
        convo_dir = os.path.join(gpts_root, convo_name)
        if not os.path.isdir(convo_dir):
            continue

        # ── Step 2: Record starting coordinate for this key ────────────────
        index_mapping.append((convo_name, current_coord_str))
        print(f"\n--- Processing '{convo_name}' from {current_coord_str} ---")

        # Seed the nav path from that coordinate
        nav.default(key=convo_name, start=current_coord_str)
        dm.attachments_source_dir = convo_dir

        # Load conversation JSON
        json_files = [f for f in os.listdir(convo_dir) if f.endswith(".json")]
        if not json_files:
            print(f"⚠️ No .json in {convo_dir}, skipping.")
            continue
        with open(os.path.join(convo_dir, json_files[0]), "r", encoding="utf-8") as f:
            convo = json.load(f)

        messages = convo.get("messages", [])
        attachments = convo.get("attachments", [])

        coord_inst = Coordinate()
        current_coord_str = coord_inst.strCoord_conv(nav.active_path.coord_dec)
        current_universe = nav.active_path.imag
        blocks_count = 0

        for i in range(0, len(messages), 2):
            user_msg = messages[i].get("content", "")
            bot_msg = messages[i + 1].get("content", "") if i + 1 < len(messages) else ""

            used_atts = [
                att for att in attachments
                if att in user_msg or att in bot_msg
            ]

            block = BlockData(
                block={"user": user_msg, "assistant": bot_msg},
                universe=current_universe,
                attachments=used_atts
            )

            dm.create_coordinate_block(current_coord_str, block)
            blocks_count += 1

            # Step forward
            current_coord_str = nav.active_path.step()
            current_universe = nav.active_path.imag

        print(f"✅ '{convo_name}': stored {blocks_count} blocks; ended at {current_coord_str}")

    # ── Step 3: Save conversation index ────────────────────────────────────
    idx_path = os.path.join(data_root, "conversation_index.txt")
    os.makedirs(data_root, exist_ok=True)
    with open(idx_path, "w", encoding="utf-8") as f:
        for key, coord in index_mapping:
            f.write(f"{key}: {coord}\n")

    print(f"\n🗂️  Wrote conversation index to '{idx_path}'")
    print("📜 Conversation start coordinates:")
    for key, coord in index_mapping:
        print(f"  • {key}: {coord}")

    print("\n🎉 All conversations processed.")
    

# ── Main Menu ───────────────────────────────────────────────────────────────
def main():
    print("=== NavigationHub + DataManager ===")
    print("1) store one     — import a single convo directory")
    print("2) restore       — replay & print a stored convo")
    print("3) recurse store — import all GPTSorted subfolders")
    choice = input("Select mode (1/2/3): ").strip()

    if choice == "1":
        store_conversation()
    elif choice == "2":
        restore_conversation()
    elif choice == "3":
        store_all_conversations()
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
