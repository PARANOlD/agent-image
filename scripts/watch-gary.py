#!/usr/bin/env python3
"""Live view of Gary's chat activity, so you don't have to read raw docker logs.

Tails chat-bridge and prints who said what, how long Gary took to answer, and
anything that went wrong -- filtering out the routine GitHub-poll retry noise.

    ./scripts/watch-gary.py            # normal view
    ./scripts/watch-gary.py --all      # include suppressed noise, unparsed lines
    ./scripts/watch-gary.py --no-bell  # don't beep on an incoming message
    ./scripts/watch-gary.py --since 1h # backfill before following

Ctrl-C to quit.
"""
from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

C = {
    "dim": "\033[2m", "reset": "\033[0m", "bold": "\033[1m",
    "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
    "red": "\033[31m", "magenta": "\033[35m", "grey": "\033[90m",
}

# "chat-bridge-1  | 2026-09-15 22:05:36,189 app INFO New conversation for ..."
LINE = re.compile(
    r"^\S+\s*\|\s*(?P<date>\d{4}-\d\d-\d\d)\s(?P<time>\d\d:\d\d:\d\d),\d+\s"
    r"(?P<logger>\S+)\s(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s(?P<msg>.*)$"
)
IN_OUT = re.compile(r"^(?P<dir>IN|OUT) (?P<surface>\w+)/(?P<thread>\S+) \| (?P<body>.*)$")

# Routine and self-healing: GitHub closes idle keep-alive connections roughly
# every poll, and the session retries transparently. Not worth a line each time.
NOISE = (
    "urllib3.connectionpool",
    "Watching [",
    "Transient error polling conversation",
)


def supports_colour() -> bool:
    return sys.stdout.isatty()


def paint(text: str, *styles: str) -> str:
    if not supports_colour():
        return text
    return "".join(C[s] for s in styles) + text + C["reset"]


def wrap_body(body: str, indent: str = " " * 12, width: int = 96) -> str:
    out, line = [], ""
    for word in body.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return f"\n{indent}".join(out) if out else body


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--all", action="store_true", help="show suppressed noise and unparsed lines")
    ap.add_argument("--no-bell", action="store_true", help="don't beep on incoming messages")
    ap.add_argument("--since", default="5m", help="how far back to backfill (default 5m)")
    args = ap.parse_args()

    # Line-buffer so output still appears promptly when piped to tee/a file,
    # not just when attached to a terminal.
    sys.stdout.reconfigure(line_buffering=True)

    repo = Path(__file__).resolve().parent.parent
    cmd = ["docker", "compose", "logs", "-f", "--since", args.since, "chat-bridge"]

    print(paint("  Gary — live activity", "bold"), paint("(ctrl-c to quit)", "dim"))
    print(paint("  " + "─" * 70, "grey"))

    # Start of an inbound message per thread, so we can report response time.
    started: dict[str, float] = {}

    proc = subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    signal.signal(signal.SIGINT, lambda *_: (proc.terminate(), sys.exit(0)))

    for raw in proc.stdout:
        raw = raw.rstrip("\n")
        if not args.all and any(n in raw for n in NOISE):
            continue

        m = LINE.match(raw)
        if not m:
            if args.all:
                print(paint("  " + raw, "grey"))
            continue

        ts, logger, level, msg = m["time"], m["logger"], m["level"], m["msg"]
        stamp = paint(f"  {ts}", "grey")

        io = IN_OUT.match(msg)
        if io:
            where = f"{io['surface']} {io['thread']}"
            if io["dir"] == "IN":
                started[io["thread"]] = time.time()
                if not args.no_bell:
                    sys.stdout.write("\a")
                print(f"{stamp} {paint('▸ in ', 'cyan', 'bold')} {paint(where, 'dim')}")
                print(f"            {paint(wrap_body(io['body']), 'cyan')}")
            else:
                began = started.pop(io["thread"], None)
                took = f"  {time.time() - began:.0f}s" if began else ""
                print(f"{stamp} {paint('◂ out', 'green', 'bold')} {paint(where + took, 'dim')}")
                print(f"            {wrap_body(io['body'])}")
            continue

        if "staying quiet" in msg:
            print(f"{stamp} {paint('· quiet', 'grey')} {paint('judged not directed at Gary', 'dim')}")
        elif msg.startswith("New conversation"):
            print(f"{stamp} {paint('+ new', 'magenta')} {paint(msg.split('for ', 1)[-1], 'dim')}")
        elif msg.startswith("Continuing conversation"):
            print(f"{stamp} {paint('~ cont', 'magenta')} {paint(msg.split('for ', 1)[-1], 'dim')}")
        elif "Bolt app is running" in msg:
            print(f"{stamp} {paint('⚑ up  ', 'magenta', 'bold')} {paint('chat-bridge connected to Slack', 'dim')}")
        elif level in ("ERROR", "CRITICAL"):
            print(f"{stamp} {paint('✗ err ', 'red', 'bold')} {paint(f'{logger}: {msg}', 'red')}")
        elif level == "WARNING":
            print(f"{stamp} {paint('! warn', 'yellow')} {paint(f'{logger}: {msg}', 'dim')}")
        elif args.all:
            print(f"{stamp} {paint(f'  {logger}: {msg}', 'grey')}")

    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
