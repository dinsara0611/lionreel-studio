import sys
import re

def search(filename, pattern):
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        for idx, line in enumerate(f, 1):
            if re.search(pattern, line, re.IGNORECASE):
                print(f"{idx}: {line.strip()[:140]}")

if __name__ == '__main__':
    search(sys.argv[1], sys.argv[2])
