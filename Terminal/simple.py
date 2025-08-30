# token_budget_writer.py
# Minimal interactive "LLM-offline" writer with a token budget tied to the input.

import re

# --- Tokenizer: words and punctuation as tokens (transparent + deterministic) ---
# e.g., "Saturn’s rings, wow!" -> ["Saturn", "s", "rings", ",", "wow", "!"]
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text or "")

def detokenize(tokens: list[str]) -> str:
    """
    Join tokens with a small rule:
      - no extra space before punctuation
      - space between alphanumerics/punct where natural
    This is deliberately simple (and reversible-ish for count checking).
    """
    out = []
    for i, tok in enumerate(tokens):
        if i == 0:
            out.append(tok)
            continue
        # If current token is punctuation, no leading space.
        if TOKEN_PATTERN.fullmatch(tok) and not tok.isalnum():
            out.append(tok)
        else:
            # If previous token was punctuation (no trailing space), add space.
            prev = out[-1]
            if prev and TOKEN_PATTERN.fullmatch(prev) and not prev.isalnum():
                out.append(" " + tok)
            else:
                out.append(" " + tok)
    return "".join(out)

# --- Core utilities ---

def token_count(text: str) -> int:
    return len(tokenize(text))

def truncate_to_budget(tokens: list[str], budget: int) -> list[str]:
    return tokens[:max(0, budget)]

def interactive_token_writer(budget: int) -> str:
    """
    Interactive line-by-line composer.
    - Shows tokens used/left after each line.
    - If you exceed the budget, extra tokens are safely truncated.
    - Finish by submitting an empty line.
    """
    print(f"[Token Budget] {budget} tokens")
    composed_tokens: list[str] = []

    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n[Ended]")
            break

        if line.strip() == "":
            # Finish on blank line
            break

        # Add new line as tokens (we treat a newline as a space boundary)
        new_tokens = tokenize(line)
        remaining = budget - len(composed_tokens)

        if remaining <= 0:
            print("[Budget Reached] Additional text will be ignored. Press Enter to finish.")
            continue

        if len(new_tokens) > remaining:
            # Truncate to fit
            fitting = new_tokens[:remaining]
            composed_tokens.extend(fitting)
            print(f"[Used {budget}/{budget}] 0 left (truncated excess)")
            # Budget is full; allow user to press blank line to finish
        else:
            composed_tokens.extend(new_tokens)
            used = len(composed_tokens)
            left = max(0, budget - used)
            print(f"[Used {used}/{budget}] {left} left")

    return detokenize(composed_tokens)

def write_with_same_token_budget(input_text: str) -> str:
    """
    Convenience wrapper:
    - Derives budget from input_text token count
    - Launches interactive writer
    """
    budget = token_count(input_text)
    return interactive_token_writer(budget)

# --- Optional: non-interactive helpers ---

def enforce_same_token_count(input_text: str, response_text: str) -> str:
    """
    If you already have a response string, trim or pad (with the minimal '…')
    so that its token count equals the input's token count.
    """
    in_budget = token_count(input_text)
    resp_tokens = tokenize(response_text)

    if len(resp_tokens) == in_budget:
        return response_text

    if len(resp_tokens) > in_budget:
        return detokenize(truncate_to_budget(resp_tokens, in_budget))

    # Pad with a single ellipsis token if short (keeps behavior obvious)
    pad_needed = in_budget - len(resp_tokens)
    padded = resp_tokens + (["…"] * pad_needed)
    return detokenize(padded)

# --- Demo when run directly ---
if __name__ == "__main__":
    moment = input("Input description of current moment:\n> ").strip()
    if not moment:
        print("No input. Exiting.")
    else:
        print("\nCompose a response with the same token count. Submit an empty line to finish.\n")
        out = write_with_same_token_budget(moment)
        print("\n--- RESULT (same token count) ---")
        print(out)
        print(f"\n[Input tokens = {token_count(moment)} | Output tokens = {token_count(out)}]")
