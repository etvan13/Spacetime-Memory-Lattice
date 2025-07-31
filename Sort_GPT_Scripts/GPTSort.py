import json
import re
import shutil
import sys
import time
from pathlib import Path
from slugify import slugify
from html import unescape
from collections import defaultdict

# ── CONFIG ───────────────────────────────────────────────────────────

THIS_DIR = Path(__file__).resolve().parent
BASE_DIR = THIS_DIR.parent

ROOT_DIR     = BASE_DIR / "GPTData"
CONV_JSON    = ROOT_DIR / "conversations.json"
ASSETS_JSON  = ROOT_DIR / "assets.json"
OUT_DIR      = BASE_DIR / "Sorted_GPT_Data"
DELTA_DIR    = BASE_DIR / "delta"
NEW_DELTA    = DELTA_DIR / "new_chats"
APPEND_DELTA = DELTA_DIR / "appending"
MAX_SLUG     = 80

# ── UTILS ────────────────────────────────────────────────────────────

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

def progress_bar(i, total, note=""):
    bar_len = 40
    filled = int(bar_len * i / total)
    bar = "#" * filled + "-" * (bar_len - filled)
    print(f"\r[{bar}] {i}/{total} {note}", end="", flush=True)

# ── MAIN ─────────────────────────────────────────────────────────────

def main():
    if not CONV_JSON.exists() or not ASSETS_JSON.exists():
        print("❌ Missing conversations.json or assets.json. (run extractor.py)")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    NEW_DELTA.mkdir(parents=True, exist_ok=True)
    APPEND_DELTA.mkdir(parents=True, exist_ok=True)

    convs  = json.loads(CONV_JSON.read_text(encoding="utf-8"))
    assets = json.loads(ASSETS_JSON.read_text(encoding="utf-8"))

    existing_ids = {}
    for folder in OUT_DIR.glob("*--*"):
        meta_file = next(folder.glob("*.json"), None)
        if not meta_file:
            continue
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            if "id" in data:
                existing_ids[data["id"]] = {
                    "path": meta_file,
                    "messages": data.get("messages", [])
                }
        except Exception:
            continue

    updated, skipped, errors = 0, 0, []

    total = len(convs)
    for idx, conv in enumerate(convs, 1):
        title = conv.get("title") or "Untitled"
        conv_id = conv.get("conversation_id")
        clean_title = clean(title)
        folder_name = f"{clean_title}--{conv_id}"
        folder = OUT_DIR / folder_name
        out_json = folder / f"{clean_title}.json"

        try:
            messages = extract_msgs(conv, assets)
            clean_content(messages)
            messages = group_messages(messages)

            if conv_id in existing_ids:
                existing = existing_ids[conv_id]["messages"]
                if len(messages) < len(existing):
                    skipped += 1
                    progress_bar(idx, total, "🔹 skipped (truncated)")
                    continue
                if messages[:len(existing)] == existing:
                    if len(messages) == len(existing):
                        skipped += 1
                        progress_bar(idx, total, "🔹 skipped (same)")
                        continue
                    # Append case
                    delta_msgs = messages[len(existing):]

                    # copy any brand-new attachments
                    new_atts = extract_attachments(delta_msgs)
                    for fn in new_atts:
                        dst = folder / fn
                        if not dst.exists():
                            src = find_file(fn, ROOT_DIR)
                            if src: shutil.copy(src, dst)

                    folder.mkdir(parents=True, exist_ok=True)
                    full_atts = extract_attachments(messages)

                    json.dump({
                        "title": title,
                        "id": conv_id,
                        "create_time": conv.get("create_time"),
                        "model": conv.get("model"),
                        "message_count": len(messages),
                        "attachments": sorted(list(full_atts)),
                        "messages": messages
                    }, out_json.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)

                    delta_folder = APPEND_DELTA / folder_name
                    delta_folder.mkdir(parents=True, exist_ok=True)
                    delta_path = delta_folder / f"{clean_title}.json"
                    json.dump({
                        "id": conv_id,
                        "title": clean_title,
                        "new_message_count": len(delta_msgs),
                        "messages": delta_msgs
                    }, delta_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)

                    updated += 1
                    progress_bar(idx, total, "✅ updated")
                    continue

            # New conversation
            folder.mkdir(parents=True, exist_ok=True)
            attachments = extract_attachments(messages)
            for fn in attachments:
                src = find_file(fn, ROOT_DIR)
                if src:
                    shutil.copy(src, folder / fn)

            json.dump({
                "title": title,
                "id": conv_id,
                "create_time": conv.get("create_time"),
                "model": conv.get("model"),
                "message_count": len(messages),
                "attachments": sorted(list(attachments)),
                "messages": messages
            }, out_json.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)

            delta_folder = NEW_DELTA / folder_name
            delta_folder.mkdir(parents=True, exist_ok=True)
            delta_path = delta_folder / f"{clean_title}.json"
            json.dump({
                "title": title,
                "id": conv_id,
                "create_time": conv.get("create_time"),
                "model": conv.get("model"),
                "message_count": len(messages),
                "attachments": sorted(list(attachments)),
                "messages": messages
            }, delta_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)

            updated += 1
            progress_bar(idx, total, "✨ added")

        except Exception as e:
            errors.append((title, str(e)))
            progress_bar(idx, total, "❌ error")

    print(f"\n✅ Done. {updated} updated or added, {skipped} skipped, {len(errors)} errors.")
    for title, msg in errors:
        print(f"⚠️  {title}: {msg}")

if __name__ == "__main__":
    main()
