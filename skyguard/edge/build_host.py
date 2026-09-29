import sys
import os

def main():
    print("Error: GCC is not available on this system to compile edge testing binaries. Cannot measure object size or parity.", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
