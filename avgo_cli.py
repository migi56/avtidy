from __future__ import annotations

import argparse
from pathlib import Path

from avgo import __version__
from avgo.core import (
    MODE_NEW_ONLY,
    MODE_REBUILD_CATALOG,
    MODE_RESCAN_ALL,
    MODE_RESCAN_MISSING,
    summarize_result,
    sync_library,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create info.md files and rebuild catalog.md for a video library.")
    parser.add_argument("root", nargs="?", help="Video library root directory.")
    parser.add_argument("--rescan-missing", action="store_true", help="Only refresh existing info.md files that are missing key fields.")
    parser.add_argument("--rescan-all", action="store_true", help="Rewrite all existing info.md files.")
    parser.add_argument("--rebuild-catalog", action="store_true", help="Only rebuild catalog.md without touching info.md files.")
    parser.add_argument("--download-cover", action="store_true", help="Download cover images when extra.cover_url is available.")
    parser.add_argument("--preview-delete", action="store_true", help="Preview unrelated files that would be deleted, but do not delete them.")
    parser.add_argument("--version", action="version", version=f"AVGO {__version__}")
    return parser.parse_args()


def resolve_mode(args: argparse.Namespace) -> str:
    selected = [args.rescan_missing, args.rescan_all, args.rebuild_catalog]
    if sum(bool(item) for item in selected) > 1:
        raise SystemExit("Only one mode flag can be used at a time.")
    if args.rebuild_catalog:
        return MODE_REBUILD_CATALOG
    if args.rescan_all:
        return MODE_RESCAN_ALL
    if args.rescan_missing:
        return MODE_RESCAN_MISSING
    return MODE_NEW_ONLY


def main() -> int:
    args = parse_args()
    if not args.root:
        raise SystemExit("root is required unless using --version")
    result = sync_library(
        Path(args.root).expanduser().resolve(),
        resolve_mode(args),
        download_cover=args.download_cover,
        preview_delete=args.preview_delete,
    )
    print(summarize_result(result, download_cover=args.download_cover, preview_delete=args.preview_delete))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
