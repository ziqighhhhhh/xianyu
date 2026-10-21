"""Manual LWP probe: python scripts/lwp_probe.py --token ... [--text ...]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fap.platform import lwp, lwp_frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe goofish LWP register/text frames")
    parser.add_argument("--token", required=True, help="access token from mtop login.token")
    parser.add_argument("--conversation", default="", help="conversation id")
    parser.add_argument("--receiver", default="", help="receiver user id")
    parser.add_argument("--text", default="", help="optional text message")
    parser.add_argument("--timeout", type=float, default=6.0)
    args = parser.parse_args()
    frames = [lwp_frames.build_register_frame()]
    if args.text:
        if not args.conversation or not args.receiver:
            parser.error("--text requires --conversation and --receiver")
        frames.append(lwp_frames.build_text_frame(args.conversation, args.receiver, args.text))
    result = lwp.exchange(args.token, frames, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("connected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
