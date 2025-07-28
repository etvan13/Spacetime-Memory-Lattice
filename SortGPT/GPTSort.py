import json
import re
import shutil
from pathlib import Path
from slugify import slugify
from html import unescape

# ── CONFIG ───────────────────────────────────────────────────
# assume this script is run from SortGPT/
ROOT_DIR    = Path.cwd() / "GPTData"
CONV_JSON   = ROOT_DIR / "conversations.json"
ASSETS_JSON = ROOT_DIR / "assets.json"
# place sorted output at project_root/GPTSorted
OUT_DIR     = ROOT_DIR.parent.parent / "GPTSorted"
MAX_SLUG    = 80
# ──────────────────────────────────────────────────────────────────────────────

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

        # Content extraction
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
        
        # Metadata
        message_id = msg.get("id", "")
        timestamp = msg.get("create_time", 0.0)

        msgs.append({
            "role": speaker,
            "content": content,
            "timestamp": timestamp,
            "id": message_id,
            "parent": node.get("parent", "")
        })

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
                # stop reading once real content begins
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

    convs  = json.loads(CONV_JSON.read_text(encoding="utf-8"))
    assets = json.loads(ASSETS_JSON.read_text(encoding="utf-8"))

    for conv in convs:
        title = conv.get("title") or "Untitled"
        slug  = clean(title)
        folder = OUT_DIR / slug
        folder.mkdir(exist_ok=True)

        # Process messages
        messages = extract_msgs(conv, assets)
        clean_content(messages)
        messages = group_messages(messages)

        # Handle attachments
        attachments = extract_attachments(messages)
        for fn in attachments:
            src = find_file(fn, ROOT_DIR)
            if src:
                shutil.copy(src, folder / fn)
            else:
                print(f"⚠️  Potentially missed asset: {fn} in '{title}' (could just be a [File]: (text) reference in content)")

        # Save conversation as JSON
        out_file = folder / f"{slug}.json"
        with out_file.open("w", encoding="utf-8") as f:
            json.dump({
                "title": title,
                "attachments": sorted(list(attachments)),
                "messages": messages
            }, f, ensure_ascii=False, indent=2)

    print(f"✅ Exported {len(convs)} conversations to '{OUT_DIR}'")

if __name__ == "__main__":
    main()
