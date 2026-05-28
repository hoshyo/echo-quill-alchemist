"""Open the Echo-Quill dashboard in the user's default browser."""
from __future__ import annotations

import platform
import subprocess
import sys
import webbrowser

from _paths import FRONTEND_URL


def main() -> int:
    url = FRONTEND_URL
    sysname = platform.system()
    try:
        if sysname == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
        elif sysname == "Darwin":
            subprocess.Popen(["open", url])
        else:
            # generic Linux fallback
            if not webbrowser.open(url):
                subprocess.Popen(["xdg-open", url])
        print(f"[open_dashboard] opened {url}")
        return 0
    except Exception as e:
        print(f"[open_dashboard] failed to open browser: {e}", file=sys.stderr)
        print(f"[open_dashboard] please open manually: {url}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
