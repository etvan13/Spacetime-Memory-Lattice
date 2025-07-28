import json
import re
import shutil
from pathlib import Path
from slugify import slugify
from html import unescape

# ── CONFIG ──────────────────────────────────────────────────
ROOT_DIR    = Path.cwd() / "GPTData"
CONV_JSON   = ROOT_DIR / "conversations.json"
ASSETS_JSON = ROOT_DIR / "assets.json"
OUT_DIR     = ROOT_DIR.parent.parent / "GPTSorted"
MAX_SLUG    = 80

# ── UTILS ──────────────────────────────────────────

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

    titles = sorted({conv.get("title") for conv in convs if conv.get("title")})

    print("\nAvailable conversation titles:")
    for t in titles:
        print(" -", t)

    user_input = input("\nEnter the exact title of the conversation to store: ").strip()
    target = next((c for c in convs if c.get("title") == user_input), None)

    if not target:
        print("❌ Conversation not found.")
        return

    slug    = clean(user_input)
    folder  = OUT_DIR / slug
    out_json = folder / f"{slug}.json"

    messages = extract_msgs(target, assets)
    clean_content(messages)
    messages = group_messages(messages)

    if out_json.exists():
        with open(out_json, "r", encoding="utf-8") as f:
            old = json.load(f)
        old_msgs = old.get("messages", [])

        if len(messages) == len(old_msgs):
            identical = all(m1 == m2 for m1, m2 in zip(messages, old_msgs))
            if identical:
                print("✅ Conversation already stored. No changes detected.")
                choice = input(f"   Force creation of new version (e.g., {slug}1)? [y/N]: ").strip().lower()
                if choice != "y":
                    return
                i = 1
                while True:
                    new_slug = f"{slug}{i}"
                    new_folder = OUT_DIR / new_slug
                    new_json = new_folder / f"{new_slug}.json"
                    if not new_json.exists():
                        folder = new_folder
                        out_json = new_json
                        slug = new_slug
                        break
                    i += 1
            else:
                print("⚠️  Conversation with same title exists but differs from new version.")
                print("   Option 1: Append (if safe). Option 2: Force new copy.")
                choice = input("   Force creation of new version (e.g., convo1)? [y/N]: ").strip().lower()
                if choice == "y":
                    i = 1
                    while True:
                        new_slug = f"{slug}{i}"
                        new_folder = OUT_DIR / new_slug
                        new_json = new_folder / f"{new_slug}.json"
                        if not new_json.exists():
                            folder = new_folder
                            out_json = new_json
                            slug = new_slug
                            break
                        i += 1
                else:
                    return

    folder.mkdir(exist_ok=True)

    attachments = extract_attachments(messages)
    for fn in attachments:
        src = find_file(fn, ROOT_DIR)
        if src:
            shutil.copy(src, folder / fn)
        else:
            print(f"⚠️  Missing asset: {fn}")

    out_data = {
        "title": user_input,
        "id": target.get("conversation_id"),
        "create_time": target.get("create_time"),
        "model": target.get("model"),
        "message_count": len(messages),
        "attachments": sorted(list(attachments)),
        "messages": messages
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"✅ Saved to '{out_json.relative_to(OUT_DIR.parent)}'")

if __name__ == "__main__":
    main()
