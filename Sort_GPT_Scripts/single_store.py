import json
import re
import shutil
from pathlib import Path
from slugify import slugify
from html import unescape

# ── CONFIG ───────────────────────────────────────────────────────────

THIS_DIR    = Path(__file__).resolve().parent
BASE_DIR    = THIS_DIR.parent
ROOT_DIR    = BASE_DIR / "GPTData"

CONV_JSON   = ROOT_DIR / "conversations.json"
ASSETS_JSON = ROOT_DIR / "assets.json"

SORTED_DIR  = BASE_DIR / "Sorted_GPT_Data"
DELTA_DIR   = BASE_DIR / "delta"  # contains subdirs new_chats/ and appending/
MAX_SLUG    = 80

# ── UTIL FUNCTIONS ───────────────────────────────────────────────────

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
        if not msg:
            continue

        parts = msg.get("content", {}).get("parts") or []
        if not parts:
            continue

        role = msg.get("author", {}).get("role")
        if role in ("assistant", "tool"):
            speaker = "assistant"
        elif role == "user" or (role == "system" and msg.get("metadata", {}).get("is_user_system_message")):
            speaker = "user"
        else:
            continue

        texts = []
        for part in parts:
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

        content   = "\n\n".join(texts).strip()
        timestamp = msg.get("create_time")
        model     = msg.get("metadata", {}).get("model_slug")

        msgs.append({
            "role":      speaker,
            "content":   content,
            "timestamp": timestamp,
            "model":     model
        })

    return list(reversed(msgs))


def extract_attachments(messages: list[dict]) -> list[str]:
    attachments = set()
    for msg in messages:
        for line in msg["content"].splitlines():
            m = re.match(r"^\[File\]:\s*([\w .()\[\]\-]+)$", line)
            if m:
                attachments.add(m.group(1))
            else:
                break
    return sorted(attachments)

def find_file(filename: str, root: Path) -> Path | None:
    return next(root.rglob(filename), None)

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
            # merge content but KEEP original timestamp+model
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
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if data.get("id") == conv_id:
                    return json_path
    return None

# ── DELTA WRITER ─────────────────────────────────────────────────────

def write_delta(slug: str,
                conv_id: str,
                blocks: list[dict],
                attachments: list[str],
                title: str,
                create_time,
                model,
                is_append: bool,
                custom_slug: str = None):
    """
    Writes a delta JSON (same structure as sorted) and copies attachments.
    """
    folder_type = "appending" if is_append else "new_chats"
    slug_use = custom_slug or slug
    delta_folder = DELTA_DIR / folder_type / f"{slug_use}--{conv_id}"
    delta_folder.mkdir(parents=True, exist_ok=True)
    # copy attachments
    for fn in attachments:
        src = find_file(fn, ROOT_DIR)
        if src:
            shutil.copy(src, delta_folder / fn)
    # write JSON
    out_data = {
        "title":           title,
        "id":              conv_id,
        "create_time":     create_time,
        "model":           model,
        "message_count":   len(blocks),
        "attachments":     attachments,
        "messages":        blocks
    }
    out_path = delta_folder / f"{slug_use}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print(f"✅ Delta saved → {out_path.relative_to(DELTA_DIR.parent)}")

# ── MAIN ──────────────────────────────────────────────────────────────

def main():
    if not CONV_JSON.exists() or not ASSETS_JSON.exists():
        print("❌ Missing conversations.json or assets.json.")
        return

    SORTED_DIR.mkdir(parents=True, exist_ok=True)
    (DELTA_DIR / "new_chats").mkdir(parents=True, exist_ok=True)
    (DELTA_DIR / "appending").mkdir(parents=True, exist_ok=True)

    convs  = json.loads(CONV_JSON.read_text(encoding="utf-8"))
    assets = json.loads(ASSETS_JSON.read_text(encoding="utf-8"))

    # choose
    print("\nAvailable conversations:")
    for c in convs:
        print(f" - {c.get('title','untitled')} [{c.get('id','')[:4]}]")
    query   = input("\nEnter partial title or ID to store: ").strip().lower()
    matches = [c for c in convs if query in (c.get("title") or "").lower() or query in c.get("id","")]
    if not matches:
        print("❌ No matching conversation found.")
        return
    if len(matches) > 1:
        print("⚠️ Multiple matches found:")
        for i,c in enumerate(matches): print(f"  [{i}] {c.get('title')} ({c.get('id')})")
        idx = input("Select index: ").strip()
        target = matches[int(idx)] if idx.isdigit() and int(idx)<len(matches) else matches[0]
    else:
        target = matches[0]
        if input(f"\nSave '{target.get('title')}--{target.get('id')}'? [y/N]: ").lower()!="y":
            print("❌ Operation cancelled.")
            return

    title       = target.get("title","untitled")
    conv_id     = target.get("id")
    create_time = target.get("create_time")
    model       = target.get("model")
    slug        = clean(title)
    slug_id     = f"{slug}--{conv_id}"
    folder      = SORTED_DIR / slug_id
    out_json    = folder / f"{slug}.json"

    msgs        = extract_msgs(target, assets)
    clean_content(msgs)
    msgs        = group_messages(msgs)
    attachments = extract_attachments(msgs)

    # check existing
    old_path = find_existing_by_id(conv_id)
    was_append = False
    force_save = False
    suffix = 1
    if old_path:
        old_data = json.loads(old_path.read_text(encoding="utf-8"))
        old_msgs = old_data.get("messages",[])
        if len(msgs) == len(old_msgs):
            print("✅ Conversation already stored. No new messages.")
            if input("Force save new version? [y/N]: ").lower()=="y":
                while (SORTED_DIR/f"{slug_id}__{suffix}").exists(): suffix+=1
                folder   = SORTED_DIR / f"{slug_id}__{suffix}"
                out_json = folder / f"{slug}.json"
                force_save = True
        elif len(msgs) > len(old_msgs):
            new_msgs = msgs[len(old_msgs):]
            new_atts = extract_attachments(new_msgs)
            # update sorted
            old_data["messages"].extend(new_msgs)
            old_data["message_count"] = len(old_data["messages"])
            with open(old_path, "w", encoding="utf-8") as f:
                json.dump(old_data, f, ensure_ascii=False, indent=2)
            # delta append
            write_delta(slug, conv_id, new_msgs, new_atts, title, create_time, model, is_append=True)
            print(f"✅ Appended {len(new_msgs)} new messages.")
            return
        else:
            print("⚠️ New data has fewer messages than stored copy. Skipping.")
            return

    # new or force-save
    folder.mkdir(parents=True, exist_ok=True)
    for fn in attachments:
        src = find_file(fn, ROOT_DIR)
        if src: shutil.copy(src, folder/fn)
        else: print(f"⚠️ Missing asset: {fn}")

    final_id = conv_id if not force_save else f"{conv_id}_{suffix}"
    out_data = {
        "title":         title,
        "id":            final_id,
        "create_time":   create_time,
        "model":         model,
        "message_count": len(msgs),
        "attachments":   attachments,
        "messages":      msgs
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    custom = slug_id if not force_save else f"{slug_id}__{suffix}"
    write_delta(slug, final_id, msgs, attachments, title, create_time, model, is_append=False, custom_slug=custom)
    print(f"✅ Saved → {out_json.relative_to(SORTED_DIR.parent)}")

if __name__ == "__main__":
    main()
