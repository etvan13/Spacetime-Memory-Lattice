# probdrive_cli.py
# Minimal, pluggable LLM-command router with equal-length ("equal-mass") option.

import os, sys, textwrap, random

# -----------------------
# 1) Replace this with your LLM provider call.
#    Make sure to return a plain string.
# -----------------------
def llm(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
    """
    Stub LLM call.
    Plug in your provider here. For example (pseudo):
      from openai import OpenAI
      client = OpenAI()
      resp = client.chat.completions.create(
          model="gpt-4.1",
          messages=[{"role":"system","content":system_prompt},
                    {"role":"user","content":user_prompt}],
          temperature=0.8,
          max_tokens=max_tokens
      )
      return resp.choices[0].message.content.strip()
    """
    # TEMP fake response so you can run without an API:
    # (You’ll immediately see structure is working.)
    canned = [
        "A silent capsule slips beyond Saturn’s rings, nudged by unseen currents.",
        "The vessel hovers near Saturn, panels drinking in stray energies as momentum.",
        "The moment refracts: same mass, new orientation, equal and opposite impression."
    ]
    return random.choice(canned)

# -----------------------
# 2) Helpers
# -----------------------
def equalize_length(text: str, target_len: int) -> str:
    """Trim or softly pad to exactly target_len characters."""
    t = text.strip().replace("\n", " ")
    if len(t) == target_len:
        return t
    if len(t) > target_len:
        # Trim with ellipsis if needed
        cut = max(0, target_len - 1)
        return (t[:cut].rstrip() + "…")[:target_len]
    # Pad
    pad_needed = target_len - len(t)
    # Prefer one ellipsis then spaces
    filler = (" …" if pad_needed >= 2 else " ")
    while len(t) + len(filler) < target_len:
        filler += " "
    return (t + filler)[:target_len]

def single_line(s: str) -> str:
    return " ".join(s.strip().split())

# -----------------------
# 3) Command registry
#    Each command provides: name, description, system prompt template,
#    whether to enforce equal-length, and a max_tokens hint.
# -----------------------
COMMANDS = {}

def register_command(
    name: str,
    description: str,
    system_template: str,
    enforce_equal: bool = True,
    max_tokens: int = 300
):
    COMMANDS[name] = {
        "description": description,
        "system_template": system_template,
        "enforce_equal": enforce_equal,
        "max_tokens": max_tokens,
    }

# --- Example commands ---

# (A) Zathura/Improbability-style “true variation as a fact”
register_command(
    name="probdrive",
    description="Emit a logically consistent variation of the input as a declarative fact (equal-mass by default).",
    system_template=single_line("""
        You are PROBDRIVE, a 'logical reality' generator. Given a user-described moment,
        respond with ONE alternative phrasing that remains logically possible within the same world.
        Rules:
        - Output must read like a fact (no hedging like 'maybe', 'could', 'might').
        - Keep it grounded in the original content but shift perspective (orientation, emphasis, hidden mechanism).
        - Maintain similar informational density (equal interpretive mass).
        - Number of words/tokens maxed out at input value's. (use all available!)
        
        You're basically just acting as a reality shuffler basing on logical 
         variations of the same moment inputted.
    """),
    enforce_equal=True,
    max_tokens=160
)

# (B) Professional “separate potential” variant (no equal-mass needed)
register_command(
    name="seppot",
    description="State your read, then add ONE 'separate potential' professionally.",
    system_template=single_line("""
        You are SEP-POT, a professional uncertainty framer. Respond in two short sentences:
        1) Your crisp current read of the situation.
        2) 'There is a separate potential …' followed by one concrete alternative.
        Keep tone collaborative and precise. Avoid hedging words beyond that exact phrase.
    """),
    enforce_equal=False,
    max_tokens=160
)

# (C) Risk spin (keeps equal mass for fun)
register_command(
    name="riskspin",
    description="Turn the moment into a single risk-statement 'fact' with causal hint (equal-mass).",
    system_template=single_line("""
        You are RISK-SPIN. Convert the user's moment into ONE declarative risk statement that remains
        plausible from the same facts. Include a subtle causal hint ('due to …', 'as … emerges').
        One sentence only. No lists, no meta.
    """),
    enforce_equal=True,
    max_tokens=140
)

# -----------------------
# 4) CLI loop
# -----------------------
HELP = """\
Commands:
  list                         - show available commands
  run <cmd>                    - prompt for an input 'moment' and run command
  run <cmd> "<moment>"         - run directly with inline moment
  help <cmd>                   - show command description
  quit/exit                    - leave
Examples:
  run probdrive
  run probdrive "The spacecraft drifts quietly past Saturn."
  run seppot "Manager extended the deadline by 2 weeks for the API migration."
"""

def run_command(cmd_name: str, moment: str) -> str:
    if cmd_name not in COMMANDS:
        return f"Unknown command: {cmd_name}"
    cfg = COMMANDS[cmd_name]
    sys_prompt = cfg["system_template"]
    user_prompt = moment.strip()

    resp = llm(sys_prompt, user_prompt, max_tokens=cfg["max_tokens"]).strip()
    if cfg["enforce_equal"]:
        resp = equalize_length(resp, len(user_prompt))
    return resp

def main():
    print("Probability Drive CLI — minimal LLM router")
    print("Type 'list' or 'help' for usage.\n")

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not raw:
            continue
        if raw in ("quit", "exit"):
            print("bye")
            break
        if raw == "list":
            for k, v in COMMANDS.items():
                print(f"- {k}: {v['description']}")
            continue
        if raw.startswith("help"):
            parts = raw.split(maxsplit=1)
            if len(parts) == 1:
                print(HELP)
            else:
                name = parts[1].strip()
                if name in COMMANDS:
                    print(f"{name}: {COMMANDS[name]['description']}")
                else:
                    print(f"Unknown command: {name}")
            continue
        if raw.startswith("run"):
            # run <cmd> ["moment ..."]
            parts = raw.split(maxsplit=2)
            if len(parts) < 2:
                print("Usage: run <cmd> [\"moment text\"]")
                continue
            cmd = parts[1]
            if len(parts) == 2:
                moment = input("Input description of current moment:\n> ")
            else:
                moment = parts[2].strip().strip('"').strip("'")
            out = run_command(cmd, moment)
            print(out)
            continue

        # fallback
        print(HELP)

if __name__ == "__main__":
    main()
