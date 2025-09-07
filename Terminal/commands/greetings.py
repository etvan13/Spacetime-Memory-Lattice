"""Say hello to someone."""
HELP = "hello the universe (or a name): `greetings [name]`"

def run(argv, terminal):
    name = argv[0] if argv else "Universe"
    print(f"Hello, {name}!")
    # use terminal.counter if needed
    # terminal.newpage()  # available too
