#!/usr/bin/env python3
import os, sys, subprocess, shlex
from pathlib import Path
import importlib.util
from typing import Callable, Dict, Optional, List

COMMANDS_DIR = Path(__file__).parent / "commands"

# ---------------- Core registry ----------------

class Command:
    def __init__(self, name: str, runner: Callable[[List[str], "Terminal"], int], help_text: str = "", is_alias: bool = False):
        self.name = name                  # "foo", "math add"
        self.runner = runner              # (argv, terminal) -> exit code
        self.help_text = help_text.strip()
        self.is_alias = is_alias

def _module_from_path(py_path: Path):
    spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

def _name_from_rel(rel: Path) -> str:
    return " ".join(rel.with_suffix("").parts)  # "math/add.py" -> "math add"

def _python_runner(py_file: Path, help_text: str = "") -> Command:
    rel = py_file.relative_to(COMMANDS_DIR)
    name = _name_from_rel(rel)
    mod = _module_from_path(py_file)

    # Preferred signature: run(argv, terminal)
    run = getattr(mod, "run", None)
    if not callable(run):
        # Allow class-based commands: class exports CommandClass with run(self)
        if hasattr(mod, "CommandClass"):
            def wrapper(argv, terminal):
                obj = mod.CommandClass(terminal=terminal, counter=terminal.counter)
                return obj.run(argv) if obj.run.__code__.co_argcount == 2 else (obj.run() or 0)
            return Command(name, wrapper, getattr(mod, "HELP", mod.__doc__ or ""))
        return None  # not a command

    def runner(argv, terminal):
        # Try (argv, terminal) then (argv) then ()
        try:
            return run(argv, terminal)  # type: ignore[misc]
        except TypeError:
            try:
                return run(argv)        # type: ignore[misc]
            except TypeError:
                return run() or 0       # type: ignore[misc]

    return Command(name, runner, getattr(mod, "HELP", mod.__doc__ or help_text))

def _exec_runner(exe_file: Path) -> Command:
    rel = exe_file.relative_to(COMMANDS_DIR)
    name = _name_from_rel(rel)

    def runner(argv, terminal):
        # Inherit environment; provide COUNTERS/UNIVERSES for convenience
        env = os.environ.copy()
        env["OAIS_COUNTERS"] = terminal.counter.get_counters()
        env["OAIS_UNIVERSES"] = str(terminal.counter.univ_count())
        cmd = [str(exe_file)] + argv
        try:
            return subprocess.call(cmd, env=env)
        except FileNotFoundError:
            print(f"[error] Not executable: {exe_file}")
            return 127

    help_text = ""
    # Try to read first line comment for help
    try:
        with exe_file.open("r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
            if first.startswith("#") and not first.startswith("#!"):
                help_text = first.lstrip("#").strip()
    except Exception:
        pass

    return Command(name, runner, help_text)

def discover_commands() -> Dict[str, Command]:
    registry: Dict[str, Command] = {}
    if not COMMANDS_DIR.exists():
        return registry

    for path in COMMANDS_DIR.rglob("*"):
        if path.name == "__init__.py":
            continue
        if path.is_file() and path.suffix == ".py":
            cmd = _python_runner(path)
            if cmd:
                registry[cmd.name] = cmd
        elif path.is_file() and os.access(path, os.X_OK):
            # Any executable with a shebang becomes a command
            cmd = _exec_runner(path)
            registry[cmd.name] = cmd
    return registry

def print_catalog(registry: Dict[str, Command]):
    sections: Dict[str, List[Command]] = {}
    for name, cmd in registry.items():
        if cmd.is_alias:
            continue
        section = name.split(" ")[0] if " " in name else "root"
        sections.setdefault(section, []).append(cmd)

    print("\nAvailable commands:")
    for section in sorted(sections):
        print(f"\n[{section}]")
        for c in sorted(sections[section], key=lambda x: x.name):
            short = c.help_text.splitlines()[0] if c.help_text else ""
            print(f"  {c.name:<22} {short}")
    print("")

def _suggest(registry: Dict[str, Command], typed: str) -> Optional[List[str]]:
    from difflib import get_close_matches
    m = get_close_matches(typed, list(registry.keys()), n=4, cutoff=0.55)
    return m or None

# ---------------- Your Terminal shell ----------------

class Counter:
    def __init__(self):
        self.counters = [0]*6
        self.universes = 0

    def increment(self): self._update(1)
    def decrement(self): self._update(-1)

    def _update(self, delta):
        for i in range(len(self.counters)):
            self.counters[i] += delta
            if delta > 0 and self.counters[i] == 60:
                self.counters[i] = 0
                if i == len(self.counters)-1: self.universes += 1
                continue
            elif delta < 0 and self.counters[i] == -1:
                self.counters[i] = 59
                if i == len(self.counters)-1: self.universes -= 1
                continue
            break

    @staticmethod
    def parse_coordinate(coord_str: str):
        parts = coord_str.split()
        if len(parts) != 6 or not all(p.isdigit() and 0 <= int(p) < 60 for p in parts):
            raise ValueError("Expected '# # # # # #' with each < 60")
        return [int(p) for p in parts]

    def get_counters(self): return " ".join(str(c) for c in self.counters)
    def get_counters_list(self): return list(self.counters)
    def univ_count(self): return self.universes

    def baseTenConv(self, digits=None):
        if digits is None: digits = self.counters
        return sum(d*(60**i) for i,d in enumerate(digits))

    def coord_conv(self, number):
        number %= (60**6)
        digits = []
        while number > 0:
            digits.append(number % 60)
            number //= 60
        while len(digits) < 6: digits.append(0)
        return digits

    def strCoord_conv(self, number):
        return " ".join(str(d) for d in self.coord_conv(number))

    def calculate_distance(self, ref_counter):
        curr = self.baseTenConv()
        nxt = self.baseTenConv(ref_counter) if isinstance(ref_counter, list) else ref_counter.baseTenConv()
        return self.coord_conv(nxt - curr)

    # FIX: your original had self.counter.* inside Counter (undefined). Here’s a correct version:
    def calculate_final_coordinate(self, distance):
        final_base10 = self.baseTenConv() + distance
        return self.coord_conv(final_base10)

class Terminal:
    def __init__(self):
        self.counter = Counter()
        self.registry = discover_commands()
        # Built-ins as commands:
        self.registry["help"] = Command("help", lambda argv, t: (print_catalog(t.registry) or 0), "Show command catalog")
        self.registry["list"] = self.registry["help"]

    @staticmethod
    def newpage(): os.system("cls" if os.name == "nt" else "clear")

    def default_message(self):
        self.newpage()
        return f"{self.counter.get_counters()}\nType 'help' for a list of commands.\n"

    def process_line(self, line: str) -> int:
        tokens = shlex.split(line)
        if not tokens: return 0

        # Longest-prefix match for command name
        for i in range(len(tokens), 0, -1):
            name = " ".join(tokens[:i])
            if name in self.registry:
                argv = tokens[i:]
                return self.registry[name].runner(argv, self)

        print("Unknown command.")
        if (s := _suggest(self.registry, " ".join(tokens))):
            print("Did you mean:")
            for c in s: print("  ", c)
        print("Type 'help' to see available commands.")
        return 127

    def run(self):
        print(self.default_message())
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye.")
                break
            if not line: continue
            if line == "exit": break
            rc = self.process_line(line)
            if rc not in (0, None): print(f"(exit code {rc})")

if __name__ == "__main__":
    Terminal().run()
