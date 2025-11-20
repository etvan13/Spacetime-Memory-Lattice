#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
from typing import Any, Tuple, Optional

# ── Paths ──────────────────────────────────────────────────────────────
THIS_DIR = Path(__file__).resolve().parent          # GPTStoring/Sort_GPT_Scripts
BASE_DIR = THIS_DIR.parent                          # GPTStoring
DATA_DIR = BASE_DIR / "GPTData"                     # GPTStoring/GPTData
HTML_PATH = DATA_DIR / "chat.html"

# ── HTML → JSON extract helpers (no browser) ───────────────────────────
WS = r"[ \t\r\n]*"

def _unescape_js_string(s: str) -> str:
    s = s.replace(r"\/", "/").replace(r"\\", "\\").replace(r"\'", "'").replace(r"\"", '"')
    s = s.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
    return s

def _balance_from(html: str, start: int) -> str:
    n = len(html); 
    if start >= n or html[start] not in "{[": raise ValueError("Not at JSON object/array start")
    opening = html[start]; closing = "}" if opening == "{" else "]"
    depth = 0; in_str = False; quote = ""; esc = False; i = start
    while i < n:
        ch = html[i]
        if in_str:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == quote: in_str = False
        else:
            if ch in ("'", '"'): in_str = True; quote = ch
            elif ch == opening: depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0: i += 1; return html[start:i]
        i += 1
    raise ValueError("Unbalanced JSON literal")

def _find_script_json(html: str, var_name: str) -> Optional[str]:
    m = re.search(
        rf'<script[^>]*\btype\s*=\s*["\']application/json["\'][^>]*\b(id|name)\s*=\s*["\']{re.escape(var_name)}["\'][^>]*>(.*?)</script\s*>',
        html, re.IGNORECASE | re.DOTALL
    )
    return m.group(2).strip() if m else None

def _find_json_parse(html: str, var_name: str) -> Optional[str]:
    m = re.search(
        rf'(?:^|[;{{\s])(?:var|let|const|window\.)?\s*{re.escape(var_name)}\s*=\s*JSON\.parse\s*\(\s*([\'"])(.*?)\1\s*\)\s*;',
        html, re.DOTALL
    )
    return _unescape_js_string(m.group(2)) if m else None

def _find_direct_literal(html: str, var_name: str) -> Optional[str]:
    m = re.search(rf'(?:^|[;{{\s])(?:var|let|const|window\.)?\s*{re.escape(var_name)}\s*=\s*', html, re.DOTALL)
    if not m: return None
    i = m.end(); n = len(html)
    while i < n and html[i].isspace(): i += 1
    return _balance_from(html, i) if i < n and html[i] in "{[" else None

def _find_primitive(html: str, var_name: str) -> Optional[str]:
    m = re.search(
        rf'(?:^|[;{{\s])(?:var|let|const|window\.)?\s*{re.escape(var_name)}\s*=\s*({WS}(?:null|true|false|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'){WS})\s*;',
        html, re.DOTALL
    )
    if not m: return None
    val = m.group(1).strip()
    if val.startswith("'") and val.endswith("'"):
        val = json.dumps(_unescape_js_string(val[1:-1]))
    return val

def _extract_any_json(html: str, var_name: str) -> Tuple[Any, str]:
    for finder in (_find_script_json, _find_direct_literal, _find_json_parse, _find_primitive):
        s = finder(html, var_name)
        if s is not None:
            return json.loads(s), s
    raise ValueError(f"Could not locate usable JSON for {var_name}.")

# ── Assets rebuild (progress bar included) ──────────────────────────────
SCHEMES = {"file-service", "sediment"}
PTR_RE  = re.compile(r'([a-zA-Z][a-zA-Z0-9+.-]*)://([A-Za-z0-9_\-]+)')

def _collect_asset_pointers(conversations) -> set[str]:
    """Collect '<scheme>://<token>' from explicit fields and strings."""
    out = set()
    def visit(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("asset_pointer", "pointer", "sediment_pointer") and isinstance(v, str):
                    m = PTR_RE.match(v)
                    if m and m.group(1) in SCHEMES: out.add(m.group(0))
                if isinstance(v, str):
                    for m in PTR_RE.finditer(v):
                        if m.group(1) in SCHEMES: out.add(m.group(0))
                else: visit(v)
        elif isinstance(node, list):
            for v in node: visit(v)
    visit(conversations)
    return out

def _token_from_pointer(ptr: str) -> Optional[str]:
    m = PTR_RE.match(ptr)
    return m.group(2) if m and m.group(1) in SCHEMES else None

def _best_match_for_token(root: Path, token: str) -> Optional[str]:
    """Match basenames containing token, ignoring .html/.json."""
    best_rel = None; best_len = 10**9
    token_lower = token.lower()
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            low = fname.lower()
            if low.endswith(".html") or low.endswith(".json"): continue
            if token_lower in low:
                rel = str(Path(dirpath, fname).relative_to(root)).replace("\\", "/")
                if len(fname) < best_len or (len(fname) == best_len and len(rel) < len(best_rel or "")):
                    best_len, best_rel = len(fname), rel
    return best_rel

def _progress_bar(i: int, total: int, prefix: str = ""):
    """Draw a simple progress bar in terminal."""
    bar_len = 40
    filled = int(bar_len * i / total)
    bar = "#" * filled + "-" * (bar_len - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {i}/{total}")
    sys.stdout.flush()

def _rebuild_assets(conversations, root: Path) -> dict:
    pointers = sorted(_collect_asset_pointers(conversations))
    total = len(pointers)
    if not total:
        return {}
    out = {}
    for i, ptr in enumerate(pointers, 1):
        token = _token_from_pointer(ptr)
        if token:
            rel = _best_match_for_token(root, token)
            if rel:
                out[ptr] = rel
        if i % 5 == 0 or i == total:
            _progress_bar(i, total, prefix="Rebuilding assets")
    print()  # newline after bar
    return out

# ── Main ───────────────────────────────────────────────────────────────
def main():
    if not HTML_PATH.exists():
        raise FileNotFoundError(f"Missing file: {HTML_PATH}")

    html = HTML_PATH.read_text(encoding="utf-8", errors="replace")

    conversations, _ = _extract_any_json(html, "jsonData")

    try:
        assets, _ = _extract_any_json(html, "assetsJson")
    except Exception:
        assets = None

    if not isinstance(assets, dict) or not assets:
        assets = _rebuild_assets(conversations, DATA_DIR)

    (DATA_DIR / "conversations.json").write_text(json.dumps(conversations, indent=2), encoding="utf-8")
    (DATA_DIR / "assets.json").write_text(json.dumps(assets, indent=2), encoding="utf-8")

    print("Input :", HTML_PATH)
    print("Output:", DATA_DIR)
    print(f"Conversations: {'list' if isinstance(conversations, list) else type(conversations).__name__}")
    print(f"Assets map   : {len(assets) if isinstance(assets, dict) else 0} entries")
    print("✅ Extracted JSON successfully (no browser needed).")

if __name__ == "__main__":
    main()
