import json
import re
import shutil
from pathlib import Path
from slugify import slugify
from html import unescape
from collections import defaultdict

# ── CONFIG ──────────────────────────────────────────────────
ROOT_DIR    = Path.cwd() / "GPTData"
CONV_JSON   = ROOT_DIR / "conversations.json"
ASSETS_JSON = ROOT_DIR / "assets.json"
OUT_DIR     = ROOT_DIR.parent.parent / "GPTSorted"
DELTA_DIR   = ROOT_DIR.parent.parent / "GPTDelta"
MAX_SLUG    = 80

# ── UTILS ──────────────────────────────────────────

def clean(name: str) -> str:
    return slugify(name, max_length=MAX_SLUG) or "untitled"

def generate_slug_map(convs):
    title_groups = defaultdict(list)
    for conv in convs:
        title = conv.get("title") or "Untitled"
        title_groups[title].append(conv)

    slug_map = {}
    for title, group in title_groups.items():
        group.sort(key=lambda x: x.get("create_time", 0))
        for i, conv in enumerate(group):
            base = clean(title)
            suffix = "" if i == 0 else f"-{i+1}"
            slug = f"{base}{suffix}"
            slug_map[id(conv)] = slug
    return slug_map

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
        timestamp = msg.get("create_time")
        model = msg.get("metadata", {}).get("model_slug")
        msgs.append({"role": speaker, "content": content, "timestamp": timestamp, "model": model})

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
        msg["content"] = unescape(msg["content"])
        msg["content"] = msg["content"].replace("\uFFFD", "'")

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

def main():
    if not CONV_JSON.exists() or not ASSETS_JSON.exists():
        print("❌ Missing conversations.json or assets.json.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DELTA_DIR.mkdir(parents=True, exist_ok=True)

    convs  = json.loads(CONV_JSON.read_text(encoding="utf-8"))
    assets = json.loads(ASSETS_JSON.read_text(encoding="utf-8"))
    slug_map = generate_slug_map(convs)

    updated = 0
    for conv in convs:
        title = conv.get("title") or "Untitled"
        slug = slug_map[id(conv)]
        folder = OUT_DIR / slug
        out_json = folder / f"{slug}.json"

        messages = extract_msgs(conv, assets)
        clean_content(messages)
        messages = group_messages(messages)

        if out_json.exists():
            old = json.loads(out_json.read_text(encoding="utf-8"))
            old_msgs = old.get("messages", [])

            if len(messages) < len(old_msgs):
                continue  # skip truncated versions

            if messages[:len(old_msgs)] == old_msgs:
                if len(messages) == len(old_msgs):
                    continue  # exact match, no update
                # valid append case
                folder.mkdir(exist_ok=True)
                attachments = extract_attachments(messages)
                for fn in attachments:
                    src = find_file(fn, ROOT_DIR)
                    if src:
                        shutil.copy(src, folder / fn)
                    else:
                        print(f"⚠️  Potentially missed asset: {fn} in '{title}' (could just be a [File]: (text) reference in content)")
                json.dump({
                    "title": title,
                    "id": conv.get("conversation_id"),
                    "create_time": conv.get("create_time"),
                    "model": conv.get("model"),
                    "message_count": len(messages),
                    "attachments": sorted(list(attachments)),
                    "messages": messages
                }, out_json.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)

                delta_subdir = DELTA_DIR / slug
                delta_subdir.mkdir(parents=True, exist_ok=True)
                delta_path = delta_subdir / f"{slug}_delta.json"
                delta_data = messages[len(old_msgs):]
                json.dump(delta_data, delta_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
                updated += 1
                continue
            else:
                continue  # full mismatch, handled manually if needed

        # New conversation
        folder.mkdir(exist_ok=True)
        attachments = extract_attachments(messages)
        for fn in attachments:
            src = find_file(fn, ROOT_DIR)
            if src:
                shutil.copy(src, folder / fn)
            else:
                print(f"⚠️  Potentially missed asset: {fn} in '{title}' (could just be a [File]: (text) reference in content)")

        out_file = folder / f"{slug}.json"
        json.dump({
            "title": title,
            "id": conv.get("conversation_id"),
            "create_time": conv.get("create_time"),
            "model": conv.get("model"),
            "message_count": len(messages),
            "attachments": sorted(list(attachments)),
            "messages": messages
        }, out_file.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
        updated += 1

    print(f"✅ Exported {updated} new or updated conversations to '{OUT_DIR}' and deltas to '{DELTA_DIR}'")

if __name__ == "__main__":
    main()
