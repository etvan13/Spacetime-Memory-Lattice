"""Add numbers: `math add 1 2 3`"""
def run(argv, terminal):
    if not argv:
        print("usage: math add <num1> <num2> [num3 ...]")
        return 1
    try:
        nums = [float(x) for x in argv]
    except ValueError:
        print("error: all arguments must be numbers")
        return 2
    print(sum(nums))
