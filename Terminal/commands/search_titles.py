#!/usr/bin/env python3
# Minimal, no-deps TUI with fixed panes, boxed highlight, and a persistent input bar.
import sys, json, re, shutil
from pathlib import Path
from difflib import SequenceMatcher

# ---------- Tunables ----------
RESULTS_PER_PAGE = 20       # 10 left, 10 right
LEFT_COL_SIZE    = RESULTS_PER_PAGE // 2
GAP              = 3
MIN_TERM_WIDTH   = 80
PADDING_X        = 2        # left/right margin
# ------------------------------

IS_WIN = sys.platform.startswith("win")

# ---------- Key input ----------
if IS_WIN:
    import msvcrt
    def read_key():
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {
                "H":"UP","P":"DOWN","K":"LEFT","M":"RIGHT",
                "I":"PGUP","Q":"PGDN","G":"HOME","O":"END"
            }.get(ch2, None)
        if ch == "\r": return "ENTER"
        if ch == "\x1b": return "ESC"
        if ch == "\x08": return "BACKSPACE"
        return ch
else:
    import tty, termios, select
    def read_key():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                r, _, _ = select.select([sys.stdin], [], [], 0.001)
                if r and sys.stdin.read(1) == "[":
                    code = sys.stdin.read(1)
                    return {
                        "A":"UP","B":"DOWN","D":"LEFT","C":"RIGHT",
                        "5":"PGUP","6":"PGDN","H":"HOME","F":"END"
                    }.get(code, "ESC")
                return "ESC"
            if ch in ("\r", "\n"): return "ENTER"
            if ch == "\x7f": return "BACKSPACE"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

# ---------- ANSI helpers ----------
def cls():         sys.stdout.write("\x1b[2J\x1b[H")
def home():        sys.stdout.write("\x1b[H")
def move(y, x):    sys.stdout.write(f"\x1b[{y};{x}H")
def clear_line():  sys.stdout.write("\x1b[2K")
def hide_cursor(): sys.stdout.write("\x1b[?25l")
def show_cursor(): sys.stdout.write("\x1b[?25h")
def bold_on():     sys.stdout.write("\x1b[1m")
def bold_off():    sys.stdout.write("\x1b[22m")

# ---------- Search utils ----------
def extract_title(key: str) -> str:
    return key.rsplit("--", 1)[0] if "--" in key else key

def tokenize(s: str): return re.findall(r"[a-z0-9]+", s.lower())

def score_title(title: str, terms):
    tl = title.lower(); words = set(tokenize(title))
    matched = False; score = 0.0
    for t in terms:
        if t in words: score += 2.0; matched = True
        elif t in tl:  score += 1.0; matched = True
    if not matched and terms:
        sims = [SequenceMatcher(None, tl, t).ratio() for t in terms]
        score += (sum(sims)/len(sims))*0.5
    if terms and tl.startswith(terms[0]): score += 0.25
    return score

def filter_sort(items, terms):
    if not terms: return sorted(items, key=lambda x: x[1].lower())
    scored = []
    for k, t in items:
        s = score_title(t, terms)
        if s > 0: scored.append((s, k, t))
    scored.sort(key=lambda x: (-x[0], x[2].lower()))
    return [(k, t) for _, k, t in scored]

# ---------- Layout ----------
def term_size():
    w, h = shutil.get_terminal_size((MIN_TERM_WIDTH, 30))
    return max(w, MIN_TERM_WIDTH), max(h, 18)

def pane_coords():
    # Header at row 1-2, grid from row 4 .. h-3, input bar at h-1
    w, h = term_size()
    header_y = 1
    grid_top = 4
    input_y = h - 1
    return w, h, header_y, grid_top, input_y

def calc_col_widths(w):
    inner = w - 2*PADDING_X
    col_w = (inner - GAP) // 2
    return max(20, col_w)

def wrap(s, maxlen): return s if len(s) <= maxlen else s[:maxlen-1] + "…"

# ---------- Rendering ----------
def draw_header(query_terms, page, total):
    w, h, header_y, grid_top, input_y = pane_coords()
    move(header_y, PADDING_X)
    clear_line()
    bold_on()
    sys.stdout.write(f"Query: {' '.join(query_terms) if query_terms else '(all)'}")
    bold_off()
    pages = max((total-1)//RESULTS_PER_PAGE+1, 1)
    sys.stdout.write(f"  |  Results: {total}  |  Page {page+1}/{pages}")
    move(header_y+1, PADDING_X)
    clear_line()
    sys.stdout.write("─" * (w - 2*PADDING_X))

def draw_grid(matches, page, highlight, query_terms):
    w, h, header_y, grid_top, input_y = pane_coords()
    col_w = calc_col_widths(w)
    # Clear grid area
    rows_avail = (input_y - 1) - grid_top + 1
    for r in range(rows_avail):
        move(grid_top + r, 1)
        clear_line()

    start = page*RESULTS_PER_PAGE
    end   = min(start + RESULTS_PER_PAGE, len(matches))
    base  = start

    # Draw row by row (two columns)
    for i in range(RESULTS_PER_PAGE):
        row_y = grid_top + i % LEFT_COL_SIZE
        left_ix  = start + i if i < LEFT_COL_SIZE else None
        right_ix = start + i + LEFT_COL_SIZE if i < LEFT_COL_SIZE else None

        # left cell
        if left_ix is not None and left_ix < end:
            key, title = matches[left_ix]
            shown = title
            for t in sorted(query_terms, key=len, reverse=True):
                shown = re.sub(re.escape(t), lambda m: f"[{m.group(0)}]", shown, flags=re.IGNORECASE)
            text = wrap(f"[{left_ix}] {shown}", col_w)
            x = PADDING_X
            # draw box if highlighted
            if left_ix == highlight:
                move(row_y, x); sys.stdout.write("▌" + text.ljust(col_w) + "▐")
            else:
                move(row_y, x); sys.stdout.write(" " + text.ljust(col_w) + " ")

        # right cell
        if right_ix is not None and right_ix < end:
            key2, title2 = matches[right_ix]
            shown2 = title2
            for t in sorted(query_terms, key=len, reverse=True):
                shown2 = re.sub(re.escape(t), lambda m: f"[{m.group(0)}]", shown2, flags=re.IGNORECASE)
            text2 = wrap(f"[{right_ix}] {shown2}", col_w)
            x2 = PADDING_X + col_w + GAP
            if right_ix == highlight:
                move(row_y, x2); sys.stdout.write("▌" + text2.ljust(col_w) + "▐")
            else:
                move(row_y, x2); sys.stdout.write(" " + text2.ljust(col_w) + " ")

def draw_input(mode, buf):
    w, h, header_y, grid_top, input_y = pane_coords()
    move(input_y, 1); clear_line()
    if mode == "browse":
        sys.stdout.write(" [Arrows] move  [Enter] select  [Esc] search  [PgUp/PgDn] page  [Home/End] jump  [q] quit")
    else:
        bold_on(); sys.stdout.write(" Search: "); bold_off()
        sys.stdout.write(buf)

def clamp(n, lo, hi): return max(lo, min(hi, n))

# ---------- Main loop ----------
def run(json_path: Path):
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = [(k, extract_title(k)) for k in data.keys()]
    query_terms = []
    matches = filter_sort(items, query_terms)

    page = 0
    highlight = 0
    mode = "browse"
    query_buf = ""

    cls(); hide_cursor()
    try:
        while True:
            draw_header(query_terms, page, len(matches))
            draw_grid(matches, page, highlight, query_terms)
            draw_input(mode, query_buf)
            sys.stdout.flush()

            key = read_key()
            if key in ("q", "Q"):
                break

            if mode == "browse":
                if key == "DOWN":
                    if highlight < len(matches)-1:
                        highlight += 1
                        page = highlight // RESULTS_PER_PAGE
                elif key == "UP":
                    if highlight > 0:
                        highlight -= 1
                        page = highlight // RESULTS_PER_PAGE
                elif key == "LEFT":
                    colpos = highlight % RESULTS_PER_PAGE
                    if colpos >= LEFT_COL_SIZE:
                        highlight -= LEFT_COL_SIZE
                    elif highlight > 0:
                        highlight -= 1
                    page = highlight // RESULTS_PER_PAGE
                elif key == "RIGHT":
                    colpos = highlight % RESULTS_PER_PAGE
                    if colpos < LEFT_COL_SIZE and highlight + LEFT_COL_SIZE < len(matches):
                        highlight += LEFT_COL_SIZE
                    elif highlight + 1 < len(matches):
                        highlight += 1
                    page = highlight // RESULTS_PER_PAGE
                elif key == "PGUP":
                    if page > 0:
                        page -= 1
                        highlight = page*RESULTS_PER_PAGE
                elif key == "PGDN":
                    if (page+1)*RESULTS_PER_PAGE < len(matches):
                        page += 1
                        highlight = page*RESULTS_PER_PAGE
                elif key == "HOME":
                    page = 0; highlight = 0
                elif key == "END":
                    if len(matches)>0:
                        highlight = len(matches)-1
                        page = highlight // RESULTS_PER_PAGE
                elif key == "ENTER":
                    if 0 <= highlight < len(matches):
                        key_str, title = matches[highlight]
                        # Simple selection view in header space
                        w, h, header_y, grid_top, input_y = pane_coords()
                        move(header_y, PADDING_X); clear_line()
                        bold_on(); sys.stdout.write("Selected"); bold_off()
                        sys.stdout.write(f": {title}  |  key: {key_str}")
                        move(input_y, 1); clear_line()
                        sys.stdout.write(" (Press any key to return)")
                        sys.stdout.flush()
                        read_key()
                elif key == "ESC":
                    mode = "query"; query_buf = ""
                elif isinstance(key, str) and len(key) == 1 and 32 <= ord(key) <= 126:
                    mode = "query"; query_buf = key
            else:  # query mode
                if key == "ESC":
                    mode = "browse"; query_buf = ""
                elif key == "ENTER":
                    query_terms = tokenize(query_buf)
                    matches = filter_sort(items, query_terms)
                    page = 0; highlight = 0
                    mode = "browse"
                elif key == "BACKSPACE":
                    query_buf = query_buf[:-1]
                elif isinstance(key, str) and len(key) == 1 and 32 <= ord(key) <= 126:
                    query_buf += key
                # re-render just the input bar (grid/header stay)
                draw_input(mode, query_buf)
                sys.stdout.flush()
    finally:
        show_cursor()
        move(pane_coords()[1], 1)
        sys.stdout.write("\n")

def main():
    if len(sys.argv) < 2:
        print("Usage: python search_titles_tui.py /path/to/conversations.json")
        return
    p = Path(sys.argv[1]).expanduser().resolve()
    if not p.exists():
        print(f"File not found: {p}")
        return
    run(p)

if __name__ == "__main__":
    main()
