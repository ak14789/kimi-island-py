"""PyInstaller entry point for kimi-island.exe."""
import sys

from kimi_island.main import main

if __name__ == "__main__":
    sys.exit(main())
