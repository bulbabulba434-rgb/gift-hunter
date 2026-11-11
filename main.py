"""Entry point for hosts that run `python main.py` (FadeHost and similar): always-on bot mode."""
import sys

from hunter.__main__ import main

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.argv.append("loop")
    main()
