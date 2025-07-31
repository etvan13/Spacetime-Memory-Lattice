import json
import re
import shutil
from pathlib import Path
from slugify import slugify
from html import unescape

# ── CONFIG ───────────────────────────────────────────────────────────

THIS_DIR = Path(__file__).resolve().parent
BASE_DIR = THIS_DIR.parent
ROOT_DIR = BASE_DIR / "GPTData"

CONV_JSON = ROOT_DIR / "conversations.json"
ASSETS_JSON = ROOT_DIR / "assets.json"

SORTED_DIR = BASE_DIR / "Sorted_GPT_Data"
DELTA_DIR = BASE_DIR / "delta"

MAX_SLUG = 80

# ── UTILS ─────────────────────────────────────────────────────────────

def clean(name: str) -> str:
    return slugify(name, max_length=MAX_SLUG) or "untitled"

def extract_msgs(conv: dict, asset_map: dict) -> list[dict]:
    msgs = []
    mapping = conv.get("mapping", {})
    node_id = conv.get("current_node")

    while node_id:
        node = mapping.get(node_id)
        node_id = node.get("parent") if node else None
        if not node:
            break
        msg = node.get("message")
        if not msg or not msg.get("content", {}).get("parts"):
            continue
        role = msg.get("author", {}).get("role")
        if role in ("assistant", "tool"):
            speaker = "assistant"
        elif role == "user" or (role == "system" and msg.get("metadata", {}).get("is_user_system_message")):
            speaker = "user"
        else:
            continue
        texts = []
        for part in msg["content"]["parts"]:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict):
                if part.get("content_type") == "audio_transcription":
                    texts.append(f"[Transcript]: {part.get('text','')}")
                elif part.get("asset_pointer"):
                    ptr = part["asset_pointer"]
                    url = asset_map.get(ptr)
                    fname = Path(url).name if url else None
                    texts.append(f"[File]: {fname or 'MISSING'}")
        content = "\n\n".join(texts).strip()
        msgs.append({"role": speaker, "content": content})
    return list(reversed(msgs))

def extract_attachments(messages: list[dict]) -> set[str]:
    attachments = set()
    for msg in messages:
        lines = msg["content"].splitlines()
        for line in lines:
            m = re.match(r"^\[File\]:\s*([\w .()\[\]\-]+)$", line)
            if m:
                attachments.add(m.group(1))
            else:
                break
    return attachments

def find_file(filename: str, root: Path) -> Path | None:
    for p in root.rglob(filename):
        return p
    return None

def clean_content(messages: list[dict]) -> None:
    for msg in messages:
        msg["content"] = unescape(msg["content"]).replace("\uFFFD", "'")

def group_messages(msgs: list[dict]) -> list[dict]:
    if not msgs:
        return []
    grouped = []
    curr = msgs[0].copy()
    for m in msgs[1:]:
        if m["role"] == curr["role"]:
            curr["content"] += "\n\n" + m["content"]
        else:
            grouped.append(curr)
            curr = m.copy()
    grouped.append(curr)
    return grouped

def find_existing_by_id(conv_id: str) -> Path | None:
    for folder in SORTED_DIR.iterdir():
        if folder.is_dir():
            json_path = folder / f"{folder.name.split('--')[0]}.json"
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                    if old_data.get("id") == conv_id:
                        return json_path
    return None

def write_delta(slug, conv_id, new_blocks, is_append, custom_slug=None):
    folder_type = "appending" if is_append else "new_chats"
    slug_to_use = custom_slug or slug
    delta_folder = DELTA_DIR / folder_type / f"{slug_to_use}--{conv_id}"
    delta_folder.mkdir(parents=True, exist_ok=True)
    out_path = delta_folder / f"{slug_to_use}.json"
    delta_data = {
        "id": conv_id,
        "title": slug,
        "new_block_count": len(new_blocks),
        "messages": new_blocks
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(delta_data, f, ensure_ascii=False, indent=2)
    print(f"✅ Delta saved → {out_path.relative_to(DELTA_DIR.parent)}")

# ── MAIN ──────────────────────────────────────────────────────────────

def main():
    if not CONV_JSON.exists() or not ASSETS_JSON.exists():
        print("❌ Missing conversations.json or assets.json.")
        return

    SORTED_DIR.mkdir(parents=True, exist_ok=True)

    convs = json.loads(CONV_JSON.read_text(encoding="utf-8"))
    assets = json.loads(ASSETS_JSON.read_text(encoding="utf-8"))

    print("\nAvailable conversations:")
    for c in convs:
        print(f" - {c.get('title', 'untitled')} [{c.get('id', '')[:4]}]")

    user_input = input("\nEnter partial title or ID to store: ").strip().lower()
    matches = [c for c in convs if user_input in (c.get("title") or "").lower() or user_input in c.get("id", "")]

    if not matches:
        print("❌ No matching conversation found.")
        return
    elif len(matches) > 1:
        print("⚠️ Multiple matches found:")
        for i, c in enumerate(matches):
            print(f"  [{i}] {c.get('title', 'untitled')} ({c.get('id')})")
        idx = input("Enter index of desired conversation: ").strip()
        if not idx.isdigit() or int(idx) >= len(matches):
            print("❌ Invalid selection.")
            return
        target = matches[int(idx)]
    else:
        target = matches[0]

    title = target.get("title", "untitled")
    conv_id = target.get("id")
    slug = clean(title)
    slug_id = f"{slug}--{conv_id}"
    folder = SORTED_DIR / slug_id
    out_json = folder / f"{slug}.json"

    messages = extract_msgs(target, assets)
    clean_content(messages)
    messages = group_messages(messages)
    attachments = extract_attachments(messages)

    was_appended = False
    force_saved = False
    suffix_num = 1

    old_path = find_existing_by_id(conv_id)
    if old_path and old_path.exists():
        with open(old_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        old_msgs = old_data.get("messages", [])

        if len(messages) == len(old_msgs):
            print("✅ Conversation already stored. No new messages.")
            response = input("Force save as new version? [y/n]: ").strip().lower()
            if response != "y":
                return
            # Find next suffix
            while True:
                slug_with_suffix = f"{slug_id}__{suffix_num}"
                test_folder = SORTED_DIR / slug_with_suffix
                if not test_folder.exists():
                    break
                suffix_num += 1
            folder = SORTED_DIR / slug_with_suffix
            out_json = folder / f"{slug}.json"
            force_saved = True
        elif len(messages) > len(old_msgs):
            new_msgs = messages[len(old_msgs):]
            old_data["messages"].extend(new_msgs)
            old_data["message_count"] = len(old_data["messages"])

            with open(old_path, "w", encoding="utf-8") as f:
                json.dump(old_data, f, ensure_ascii=False, indent=2)

            was_appended = True
            write_delta(slug, conv_id, new_msgs, is_append=True)
            print(f"✅ Appended {len(new_msgs)} new messages.")
            return
        else:
            print("⚠️ New data has fewer messages than stored copy. Skipping.")
            return

    folder.mkdir(exist_ok=True)
    for fn in attachments:
        src = find_file(fn, ROOT_DIR)
        if src:
            shutil.copy(src, folder / fn)
        else:
            print(f"⚠️ Missing asset: {fn}")

    final_id = conv_id
    if force_saved:
        final_id = f"{conv_id}_{suffix_num}"

    out_data = {
        "title": title,
        "id": final_id,
        "create_time": target.get("create_time"),
        "model": target.get("model"),
        "message_count": len(messages),
        "attachments": sorted(list(attachments)),
        "messages": messages
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    custom_slug = slug_id if not force_saved else f"{slug_id}__{suffix_num}"
    write_delta(slug, final_id, messages, is_append=False, custom_slug=custom_slug)
    print(f"✅ Saved → {out_json.relative_to(SORTED_DIR.parent)}")

if __name__ == "__main__":
    main()
