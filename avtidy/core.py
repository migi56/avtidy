from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .fetcher import lookup_metadata_by_code

INFO_FILE_NAME = "info.md"
CATALOG_FILE_NAME = "catalog.md"
ACTRESSES_CATALOG_FILE_NAME = "actresses.md"
MISSING_METADATA_FILE_NAME = "missing-metadata.md"
GUI_STATE_FILE = ".avtidy_gui_state.json"
DEFAULT_BODY = "# Notes\n\n"
VIDEO_RENAME_MIN_SIZE = 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".wmv",
    ".mov",
    ".mpg",
    ".mpeg",
    ".m4v",
    ".ts",
    ".flv",
    ".webm",
}
SUMMARY_PREVIEW_LIMIT = 20

MODE_NEW_ONLY = "new_only"
MODE_RESCAN_MISSING = "rescan_missing"
MODE_RESCAN_ALL = "rescan_all"
MODE_REBUILD_CATALOG = "rebuild_catalog"
MODES = [MODE_NEW_ONLY, MODE_RESCAN_MISSING, MODE_RESCAN_ALL, MODE_REBUILD_CATALOG]
MODE_LABELS = {
    MODE_NEW_ONLY: "只處理新資料夾",
    MODE_RESCAN_MISSING: "只補缺欄位的舊資料",
    MODE_RESCAN_ALL: "全部重跑",
    MODE_REBUILD_CATALOG: "只重建 catalog.md",
}
COVER_FILE_CANDIDATES = ["cover.jpg", "cover.jpeg", "cover.png", "cover.webp", "folder.jpg"]
SUBTITLE_EXTENSIONS = {".srt"}
DATE_PREFIX_PATTERN = re.compile(r"^(\d{6})-(.+)$")
CODE_WITH_SUFFIX_PATTERN = re.compile(r"^([A-Za-z]{2,10})[-_ ]?(\d{2,5})(.*)$")
ProgressCallback = Callable[[str, int, int, str, str], None]


@dataclass
class WorkRecord:
    folder: Path
    metadata: dict[str, Any]


@dataclass
class InfoDocument:
    metadata: dict[str, Any]
    body: str


@dataclass
class SyncResult:
    root: Path
    mode: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    organized_root_files: int = 0
    renamed_videos: int = 0
    deleted_files: int = 0
    metadata_fetched: int = 0
    metadata_failed: int = 0
    cover_downloaded: int = 0
    cover_skipped: int = 0
    skipped_incomplete: int = 0
    catalog_written: bool = False
    actresses_catalog_written: bool = False
    missing_metadata_written: bool = False
    total_records: int = 0
    pending_delete_paths: list[str] = field(default_factory=list)
    missing_metadata_items: list[dict[str, Any]] = field(default_factory=list)


class FrontMatterError(ValueError):
    pass


def iso_now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def format_folder_mtime(folder: Path) -> str:
    return datetime.fromtimestamp(folder.stat().st_mtime).astimezone().replace(microsecond=0).isoformat()


def count_files(folder: Path) -> int:
    return sum(1 for child in folder.iterdir() if child.is_file())


def should_scan_folder(folder: Path) -> bool:
    return folder.is_dir() and not folder.name.startswith(".") and folder.name != "avtidy" and folder.name != "vendor"


def is_large_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and path.stat().st_size >= VIDEO_RENAME_MIN_SIZE


def split_folder_name(folder_name: str) -> tuple[str, str]:
    raw_name = folder_name.strip()
    date_match = DATE_PREFIX_PATTERN.match(raw_name)
    if date_match:
        raw_name = date_match.group(2).strip()

    match = CODE_WITH_SUFFIX_PATTERN.match(raw_name)
    if not match:
        return raw_name, ''

    prefix, number, suffix = match.groups()
    code = f"{prefix.upper()}-{number}"
    return code, suffix.rstrip()


def extract_code_from_folder_name(folder_name: str) -> str:
    code, _ = split_folder_name(folder_name)
    return code


def extract_suffix_from_folder_name(folder_name: str) -> str:
    _, suffix = split_folder_name(folder_name)
    return suffix


def normalize_folder_suffix(suffix: str) -> str:
    normalized = suffix.rstrip()
    if not normalized:
        return ''
    if normalized[0].isalnum():
        return f"-{normalized.upper()}"
    return normalized


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text))


def resolve_actress_display_name(name: str, metadata: dict[str, Any]) -> str:
    cleaned_name = str(name).strip()
    if not cleaned_name or contains_cjk(cleaned_name):
        return cleaned_name

    extra = metadata.get("extra", {})
    if not isinstance(extra, dict):
        return cleaned_name

    aliases = extra.get("actress_aliases")
    if not isinstance(aliases, dict):
        return cleaned_name

    lowered_name = cleaned_name.lower()
    for japanese_name, english_name in aliases.items():
        japanese_value = str(japanese_name).strip()
        english_value = str(english_name).strip()
        if not japanese_value or not english_value:
            continue
        if english_value.lower() == lowered_name and contains_cjk(japanese_value):
            return japanese_value

    return cleaned_name


def find_actress_english_alias(actress_name: str, works: list["WorkRecord"]) -> str:
    for record in works:
        extra = record.metadata.get("extra", {})
        if not isinstance(extra, dict):
            continue
        aliases = extra.get("actress_aliases")
        if not isinstance(aliases, dict):
            continue
        english_name = aliases.get(actress_name)
        if isinstance(english_name, str) and english_name.strip():
            return english_name.strip()
    return ""


def build_dated_folder_name(code: str, release_date: str, suffix: str = '') -> str | None:
    try:
        parsed = datetime.strptime(release_date.strip(), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    normalized_suffix = normalize_folder_suffix(suffix)
    return f"{parsed.strftime('%y%m%d')}-{code}{normalized_suffix}"


def rename_folder_with_release_date(folder: Path, metadata: dict[str, Any]) -> Path:
    code = extract_code_from_folder_name(folder.name).strip()
    suffix = str(metadata.get("folder_suffix") or extract_suffix_from_folder_name(folder.name)).strip()
    release_date = str(metadata.get("release_date") or "").strip()
    desired_name = build_dated_folder_name(code, release_date, suffix)
    if not desired_name or folder.name.lower() == desired_name.lower():
        return folder

    target = folder.parent / desired_name
    if target.exists():
        return folder

    folder.rename(target)
    return target


def organize_root_loose_video_files(root: Path) -> int:
    organized = 0
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not is_large_video_file(child):
            continue

        folder_name = child.stem.strip()
        if not folder_name:
            continue

        target_folder = root / folder_name
        if target_folder.exists() and not target_folder.is_dir():
            continue

        target_folder.mkdir(exist_ok=True)
        target_path = target_folder / child.name
        if target_path.exists():
            suffix_index = 2
            while True:
                candidate = target_folder / f"{child.stem}-{suffix_index}{child.suffix.lower()}"
                if not candidate.exists():
                    target_path = candidate
                    break
                suffix_index += 1

        child.rename(target_path)
        organized += 1

    return organized


def video_sequence_key(path: Path) -> tuple[int, int, str]:
    stem = path.stem.lower()
    match = re.search(r"(?:^|[-_\s])([a-z]|\d+)$", stem)
    if not match:
        return (2, 0, stem)

    token = match.group(1)
    if token.isdigit():
        return (0, int(token), stem)
    return (1, ord(token) - ord("a") + 1, stem)


def rename_large_video_files(folder: Path, code: str) -> int:
    renamed = 0
    large_files = sorted((child for child in folder.iterdir() if is_large_video_file(child)), key=video_sequence_key)

    multiple_files = len(large_files) > 1
    sequence = 1
    for video_path in large_files:
        suffix = video_path.suffix.lower()
        desired_name = f"{code}-{sequence}{suffix}" if multiple_files else f"{code}{suffix}"
        desired_path = folder / desired_name

        if video_path.name.lower() == desired_name.lower():
            sequence += 1
            continue

        while desired_path.exists() and desired_path.resolve() != video_path.resolve():
            sequence += 1
            desired_name = f"{code}-{sequence}{suffix}"
            desired_path = folder / desired_name

        video_path.rename(desired_path)
        renamed += 1
        sequence += 1

    return renamed


def has_incomplete_download_marker(folder: Path) -> bool:
    return any(child.is_file() and child.suffix.lower().startswith('.bc') for child in folder.iterdir())


def preview_unrelated_files(folder: Path, code: str) -> list[Path]:
    code_lower = code.lower()
    keep_names = {INFO_FILE_NAME.lower(), *(name.lower() for name in COVER_FILE_CANDIDATES)}
    pending: list[Path] = []

    for child in folder.iterdir():
        if not child.is_file():
            continue

        child_name = child.name.lower()
        if child_name in keep_names:
            continue

        if child.suffix.lower() in SUBTITLE_EXTENSIONS:
            continue

        if child.suffix.lower() in VIDEO_EXTENSIONS and child.stat().st_size >= VIDEO_RENAME_MIN_SIZE:
            normalized_stem = child.stem.lower()
            if normalized_stem == code_lower or re.fullmatch(rf"{re.escape(code_lower)}-\d+", normalized_stem):
                continue

        pending.append(child)

    return sorted(pending, key=lambda item: item.name.lower())


def cleanup_unrelated_files(folder: Path, code: str, preview_only: bool = False) -> tuple[int, list[str]]:
    pending = preview_unrelated_files(folder, code)
    pending_paths = [str(path.resolve()) for path in pending]
    if preview_only:
        return 0, pending_paths

    deleted = 0
    for path in pending:
        path.unlink()
        deleted += 1
    return deleted, pending_paths


def default_metadata(folder: Path) -> dict[str, Any]:
    code = extract_code_from_folder_name(folder.name)
    timestamp = iso_now()
    return {
        "code": code,
        "title": "",
        "actresses": [],
        "studio": "",
        "release_date": "",
        "path": f"./{folder.name}",
        "status": "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "extra": {
            "source": "",
            "source_id": "",
            "source_url": "",
            "cover_url": "",
            "aliases": [code.replace("-", ""), code.lower()],
            "folder_mtime": format_folder_mtime(folder),
            "file_count": count_files(folder),
            "runtime": "",
            "director": "",
            "series": "",
            "genres": [],
            "title_english": "",
            "actress_aliases": {},
            "folder_suffix": extract_suffix_from_folder_name(folder.name),
        },
    }


def metadata_missing_key_fields(metadata: dict[str, Any]) -> bool:
    title = str(metadata.get("title") or "").strip()
    actresses = metadata.get("actresses")
    return not title or not isinstance(actresses, list) or not any(str(item).strip() for item in actresses)


def refresh_dynamic_fields(metadata: dict[str, Any], folder: Path) -> dict[str, Any]:
    data = dict(metadata)
    data["code"] = extract_code_from_folder_name(folder.name)
    data.setdefault("title", "")
    data.setdefault("folder_suffix", extract_suffix_from_folder_name(folder.name))
    actresses = data.get("actresses")
    data["actresses"] = actresses if isinstance(actresses, list) else []
    data.setdefault("studio", "")
    data.setdefault("release_date", "")
    data["folder_suffix"] = str(data.get("folder_suffix") or extract_suffix_from_folder_name(folder.name)).strip()
    data["path"] = f"./{folder.name}"
    data.setdefault("status", "pending")
    data.setdefault("created_at", iso_now())
    data["updated_at"] = iso_now()

    extra = data.get("extra")
    if not isinstance(extra, dict):
        extra = {}
    extra.setdefault("source", "")
    extra.setdefault("source_id", "")
    extra.setdefault("source_url", "")
    extra.setdefault("cover_url", "")
    extra.setdefault("source_url_ja", "")
    extra.setdefault("runtime", "")
    extra.setdefault("director", "")
    extra.setdefault("series", "")
    extra.setdefault("title_english", "")
    aliases_map = extra.get("actress_aliases")
    extra["actress_aliases"] = aliases_map if isinstance(aliases_map, dict) else {}
    genres = extra.get("genres")
    extra["genres"] = genres if isinstance(genres, list) else []
    aliases = extra.get("aliases")
    if not isinstance(aliases, list) or not aliases:
        code_alias = str(data.get("code") or extract_code_from_folder_name(folder.name))
        extra["aliases"] = [code_alias.replace("-", ""), code_alias.lower()]
    extra["folder_mtime"] = format_folder_mtime(folder)
    extra["file_count"] = count_files(folder)
    data["extra"] = extra
    return data


def merge_lookup_metadata(metadata: dict[str, Any], fetched: dict[str, Any], force: bool) -> dict[str, Any]:
    if not fetched:
        return metadata

    data = dict(metadata)
    extra = dict(data.get("extra", {}))

    def assign(field: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        if force or not data.get(field):
            data[field] = value

    assign("code", fetched.get("code"))
    assign("title", fetched.get("title"))
    assign("studio", fetched.get("studio"))
    assign("release_date", fetched.get("release_date"))

    actresses = fetched.get("actresses")
    if isinstance(actresses, list) and actresses and (force or not data.get("actresses")):
        data["actresses"] = actresses

    extra["source"] = "javdatabase"
    if fetched.get("dvd_id"):
        extra["source_id"] = fetched["dvd_id"]
    if fetched.get("source_url"):
        extra["source_url"] = fetched["source_url"]
    if fetched.get("cover_url") and (force or not extra.get("cover_url")):
        extra["cover_url"] = fetched["cover_url"]
    if fetched.get("runtime") and (force or not extra.get("runtime")):
        extra["runtime"] = fetched["runtime"]
    if fetched.get("director") and (force or not extra.get("director")):
        extra["director"] = fetched["director"]
    if fetched.get("series") and (force or not extra.get("series")):
        extra["series"] = fetched["series"]
    if fetched.get("title_english") and (force or not extra.get("title_english")):
        extra["title_english"] = fetched["title_english"]
    genres = fetched.get("genres")
    if isinstance(genres, list) and genres and (force or not extra.get("genres")):
        extra["genres"] = genres

    actress_aliases = fetched.get("actress_aliases")
    if isinstance(actress_aliases, dict) and actress_aliases:
        current_aliases = extra.get("actress_aliases")
        merged_aliases = dict(current_aliases) if isinstance(current_aliases, dict) and not force else {}
        for japanese_name, english_name in actress_aliases.items():
            if japanese_name and english_name and (force or japanese_name not in merged_aliases):
                merged_aliases[japanese_name] = english_name
        extra["actress_aliases"] = merged_aliases

    if fetched.get("source_url_ja") and (force or not extra.get("source_url_ja")):
        extra["source_url_ja"] = fetched["source_url_ja"]

    data["extra"] = extra
    return data


def maybe_fetch_metadata(metadata: dict[str, Any], force: bool) -> tuple[dict[str, Any], bool]:
    code = str(metadata.get("code") or "").strip()
    if not code:
        return metadata, False
    try:
        fetched = lookup_metadata_by_code(code)
    except Exception:
        return metadata, False
    if not fetched:
        return metadata, False
    return merge_lookup_metadata(metadata, fetched, force=force), True


def quote_yaml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return quote_yaml_string(str(value))


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, nested in value.items():
            if isinstance(nested, dict):
                lines.append(f"{pad}{key}:")
                lines.extend(yaml_lines(nested, indent + 2))
            elif isinstance(nested, list):
                if nested:
                    lines.append(f"{pad}{key}:")
                    lines.extend(yaml_lines(nested, indent + 2))
                else:
                    lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(nested)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{pad}-")
                lines.extend(yaml_lines(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
        return lines
    return [f"{pad}{yaml_scalar(value)}"]


def render_info_md(metadata: dict[str, Any], body: str = DEFAULT_BODY) -> str:
    clean_body = body if body.strip() else DEFAULT_BODY
    if not clean_body.endswith("\n"):
        clean_body += "\n"
    return "---\n" + "\n".join(yaml_lines(metadata)) + "\n---\n\n" + clean_body


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw == "[]":
        return []
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith('"') and raw.endswith('"'):
        body = raw[1:-1]
        return body.replace('\\"', '"').replace("\\\\", "\\")
    if raw.isdigit():
        return int(raw)
    try:
        return float(raw)
    except ValueError:
        return raw


def next_non_empty_line(lines: list[str], current_index: int) -> str | None:
    for line in lines[current_index + 1 :]:
        if line.strip():
            return line
    return None


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end_marker = text.find("\n---\n", 4)
    if end_marker == -1:
        return {}, text
    lines = text[4:end_marker].splitlines()
    body = text[end_marker + len("\n---\n") :].lstrip("\n")
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    for index, line in enumerate(lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]

        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise FrontMatterError(f"Invalid list item: {line}")
            parent.append(parse_scalar(stripped[2:]))
            continue

        if ":" not in stripped:
            raise FrontMatterError(f"Invalid front matter line: {line}")

        key, raw_value = stripped.split(":", 1)
        raw_value = raw_value.strip()

        if raw_value == "":
            next_line = next_non_empty_line(lines, index)
            if next_line is not None:
                next_indent = len(next_line) - len(next_line.lstrip(" "))
                next_is_list = next_indent > indent and next_line.strip().startswith("- ")
                next_container: Any = [] if next_is_list else {}
            else:
                next_container = {}

            if not isinstance(parent, dict):
                raise FrontMatterError(f"Invalid mapping line: {line}")
            parent[key] = next_container
            stack.append((indent, next_container))
            continue

        if not isinstance(parent, dict):
            raise FrontMatterError(f"Invalid scalar line: {line}")
        parent[key] = parse_scalar(raw_value)

    return root, body


def load_info_document(info_path: Path) -> InfoDocument:
    metadata, body = parse_front_matter(info_path.read_text(encoding="utf-8"))
    return InfoDocument(metadata=metadata, body=body)


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def write_info(path: Path, metadata: dict[str, Any], body: str) -> None:
    write_text(path, render_info_md(metadata, body))


def table_cell(value: Any) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value if item)
    else:
        text = str(value or "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_catalog(records: list[WorkRecord]) -> str:
    lines = [
        "# Catalog",
        "",
        f"- Total: {len(records)}",
        f"- Updated: {iso_now()}",
        "",
        "| Code | Title | Actresses | Studio | Date | Status | Folder |",
        "|---|---|---|---|---|---|---|",
    ]

    for record in sorted(records, key=lambda item: str(item.metadata.get("code", item.folder.name)).lower()):
        metadata = record.metadata
        folder_link = f"[{record.folder.name}](./{record.folder.name}/{INFO_FILE_NAME})"
        lines.append(
            "| "
            + " | ".join(
                [
                    table_cell(metadata.get("code", "")),
                    table_cell(metadata.get("title", "")),
                    table_cell(metadata.get("actresses", [])),
                    table_cell(metadata.get("studio", "")),
                    table_cell(metadata.get("release_date", "")),
                    table_cell(metadata.get("status", "")),
                    folder_link,
                ]
            )
            + " |"
        )

    lines.append("")
    return "\n".join(lines)


def render_actresses_catalog(records: list[WorkRecord]) -> str:
    actress_map: dict[str, list[WorkRecord]] = {}
    for record in records:
        actresses = record.metadata.get("actresses")
        if not isinstance(actresses, list) or not actresses:
            actress_map.setdefault("(未標記女優)", []).append(record)
            continue

        names = [
            resolve_actress_display_name(str(item).strip(), record.metadata)
            for item in actresses
            if str(item).strip()
        ]
        if not names:
            actress_map.setdefault("(未標記女優)", []).append(record)
            continue

        for name in names:
            actress_map.setdefault(name, []).append(record)

    lines = [
        "# Actresses",
        "",
        f"- Total actresses: {len(actress_map)}",
        f"- Total works: {len(records)}",
        f"- Updated: {iso_now()}",
        "",
    ]

    for actress in sorted(actress_map, key=lambda item: item.lower()):
        works = sorted(
            actress_map[actress],
            key=lambda record: (
                str(record.metadata.get("release_date") or "9999-99-99"),
                str(record.metadata.get("code") or record.folder.name),
            ),
        )
        lines.append(f"## {actress} ({len(works)})")

        english_name = find_actress_english_alias(actress, works)
        if english_name:
            lines.append(f"- Alias: {english_name}")

        for record in works:
            metadata = record.metadata
            code = str(metadata.get("code") or record.folder.name)
            title = str(metadata.get("title") or "")
            date = str(metadata.get("release_date") or "")
            folder_link = f"[{record.folder.name}](./{record.folder.name}/{INFO_FILE_NAME})"
            summary = f"{date} | {code}"
            if title:
                summary += f" | {title}"
            lines.append(f"- {summary} | {folder_link}")

        lines.append("")

    return "\n".join(lines)


def is_suspicious_code(code: str) -> bool:
    return not bool(re.fullmatch(r'([A-Z]{2,10})-(\d{2,5})', code.strip().upper()))


def build_missing_metadata_item(folder: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    code = extract_code_from_folder_name(folder.name).strip()
    title = str(metadata.get("title") or "").strip()
    release_date = str(metadata.get("release_date") or "").strip()
    actresses = metadata.get("actresses") if isinstance(metadata.get("actresses"), list) else []
    actress_names = [str(item).strip() for item in actresses if str(item).strip()]

    reasons: list[str] = []
    if not title:
        reasons.append('缺標題')
    if not actress_names:
        reasons.append('缺女優')
    if not release_date:
        reasons.append('缺發行日期')
    if is_suspicious_code(code):
        reasons.append('疑似番號異常')

    return {
        'folder_name': folder.name,
        'code': code,
        'title': title,
        'release_date': release_date,
        'actresses': actress_names,
        'reasons': reasons,
    }


def render_missing_metadata(items: list[dict[str, Any]]) -> str:
    lines = [
        '# Missing Metadata',
        '',
        f'- Total: {len(items)}',
        f'- Updated: {iso_now()}',
        '',
    ]

    if not items:
        lines.append('- No missing metadata items.')
        lines.append('')
        return '\n'.join(lines)

    sorted_items = sorted(items, key=lambda item: item.get('folder_name', '').lower())
    for item in sorted_items:
        folder_name = str(item.get('folder_name') or '')
        code = str(item.get('code') or '')
        reasons = ', '.join(item.get('reasons') or [])
        title = str(item.get('title') or '')
        release_date = str(item.get('release_date') or '')
        actresses = ', '.join(item.get('actresses') or [])
        folder_link = f'[{folder_name}](./{folder_name}/{INFO_FILE_NAME})'

        lines.append(f'## {folder_name}')
        lines.append(f'- Code: {code}')
        lines.append(f'- Reasons: {reasons or "無"}')
        if title:
            lines.append(f'- Title: {title}')
        if actresses:
            lines.append(f'- Actresses: {actresses}')
        if release_date:
            lines.append(f'- Release date: {release_date}')
        lines.append(f'- Folder: {folder_link}')
        lines.append('')

    return '\n'.join(lines)


def format_folder_status(success_label: str, reasons: list[str]) -> str:
    if not reasons:
        return success_label

    missing_set = set(reasons)
    if missing_set == {'缺標題', '缺女優', '缺發行日期'} or missing_set == {'缺標題', '缺女優', '缺發行日期', '疑似番號異常'}:
        return f"失敗（{'、'.join(reasons)}）"

    return f"部分完成（{'、'.join(reasons)}）"


def pick_cover_extension(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".png"):
        return ".png"
    if lowered.endswith(".jpeg"):
        return ".jpeg"
    if lowered.endswith(".webp"):
        return ".webp"
    return ".jpg"


def existing_cover_path(folder: Path) -> Path | None:
    for name in COVER_FILE_CANDIDATES:
        candidate = folder / name
        if candidate.exists():
            return candidate
    return None


def download_cover_if_possible(folder: Path, metadata: dict[str, Any], download_cover: bool) -> bool:
    if not download_cover:
        return False
    if existing_cover_path(folder) is not None:
        return False
    extra = metadata.get("extra")
    if not isinstance(extra, dict):
        return False
    cover_url = str(extra.get("cover_url") or "").strip()
    if not cover_url:
        return False

    target_path = folder / f"cover{pick_cover_extension(cover_url)}"
    request = urllib.request.Request(
        cover_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False

    target_path.write_bytes(data)
    return True


def sync_library(
    root: Path,
    mode: str = MODE_NEW_ONLY,
    download_cover: bool = False,
    preview_delete: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> SyncResult:
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Root folder does not exist: {root}")

    result = SyncResult(root=root, mode=mode)
    result.organized_root_files = organize_root_loose_video_files(root)

    records: list[WorkRecord] = []
    missing_items: list[dict[str, Any]] = []
    folders = [folder for folder in sorted(root.iterdir(), key=lambda path: path.name.lower()) if should_scan_folder(folder)]
    total_folders = len(folders)

    for index, folder in enumerate(folders, start=1):
        if progress_callback is not None:
            progress_callback("start", index, total_folders, folder.name, "")

        if has_incomplete_download_marker(folder):
            result.skipped += 1
            result.skipped_incomplete += 1
            if progress_callback is not None:
                progress_callback("done", index, total_folders, folder.name, "略過（下載未完成）")
            continue

        info_path = folder / INFO_FILE_NAME

        if mode == MODE_REBUILD_CATALOG:
            if info_path.exists():
                try:
                    document = load_info_document(info_path)
                    metadata = refresh_dynamic_fields(document.metadata or default_metadata(folder), folder)
                except FrontMatterError:
                    metadata = refresh_dynamic_fields(default_metadata(folder), folder)
                folder = rename_folder_with_release_date(folder, metadata)
                info_path = folder / INFO_FILE_NAME
                result.renamed_videos += rename_large_video_files(folder, str(metadata.get("code") or extract_code_from_folder_name(folder.name)))
                deleted, pending = cleanup_unrelated_files(folder, str(metadata.get("code") or extract_code_from_folder_name(folder.name)), preview_only=preview_delete)
                result.deleted_files += deleted
                result.pending_delete_paths.extend(pending)
                metadata = refresh_dynamic_fields(metadata, folder)
                records.append(WorkRecord(folder=folder, metadata=metadata))
                missing_item = build_missing_metadata_item(folder, metadata)
                if missing_item["reasons"]:
                    missing_items.append(missing_item)
                if download_cover_if_possible(folder, metadata, download_cover):
                    result.cover_downloaded += 1
                else:
                    result.cover_skipped += 1
                if progress_callback is not None:
                    progress_callback("done", index, total_folders, folder.name, "完成（重建索引）")
            continue

        if not info_path.exists():
            metadata = refresh_dynamic_fields(default_metadata(folder), folder)
            metadata, fetched = maybe_fetch_metadata(metadata, force=True)
            if fetched:
                result.metadata_fetched += 1
            else:
                result.metadata_failed += 1
            folder = rename_folder_with_release_date(folder, metadata)
            info_path = folder / INFO_FILE_NAME
            result.renamed_videos += rename_large_video_files(folder, str(metadata.get("code") or extract_code_from_folder_name(folder.name)))
            deleted, pending = cleanup_unrelated_files(folder, str(metadata.get("code") or extract_code_from_folder_name(folder.name)), preview_only=preview_delete)
            result.deleted_files += deleted
            result.pending_delete_paths.extend(pending)
            metadata = refresh_dynamic_fields(metadata, folder)
            write_info(info_path, metadata, DEFAULT_BODY)
            records.append(WorkRecord(folder=folder, metadata=metadata))
            missing_item = build_missing_metadata_item(folder, metadata)
            if missing_item["reasons"]:
                missing_items.append(missing_item)
            result.created += 1
            if download_cover_if_possible(folder, metadata, download_cover):
                result.cover_downloaded += 1
            else:
                result.cover_skipped += 1
            if progress_callback is not None:
                progress_callback("done", index, total_folders, folder.name, format_folder_status("完成（新增）", missing_item["reasons"]))
            continue

        try:
            document = load_info_document(info_path)
            metadata = refresh_dynamic_fields(document.metadata or default_metadata(folder), folder)
            body = document.body or DEFAULT_BODY
        except FrontMatterError:
            metadata = refresh_dynamic_fields(default_metadata(folder), folder)
            body = DEFAULT_BODY

        should_fetch = False
        should_write = False
        if mode == MODE_RESCAN_ALL:
            should_fetch = True
            should_write = True
        elif mode == MODE_RESCAN_MISSING and metadata_missing_key_fields(metadata):
            should_fetch = True
            should_write = True

        if should_fetch:
            metadata, fetched = maybe_fetch_metadata(metadata, force=(mode == MODE_RESCAN_ALL))
            if fetched:
                result.metadata_fetched += 1
            else:
                result.metadata_failed += 1

        folder = rename_folder_with_release_date(folder, metadata)
        info_path = folder / INFO_FILE_NAME
        result.renamed_videos += rename_large_video_files(folder, str(metadata.get("code") or extract_code_from_folder_name(folder.name)))
        deleted, pending = cleanup_unrelated_files(folder, str(metadata.get("code") or extract_code_from_folder_name(folder.name)), preview_only=preview_delete)
        result.deleted_files += deleted
        result.pending_delete_paths.extend(pending)
        metadata = refresh_dynamic_fields(metadata, folder)

        if should_write:
            write_info(info_path, metadata, body)
            result.updated += 1
        else:
            result.skipped += 1

        records.append(WorkRecord(folder=folder, metadata=metadata))
        missing_item = build_missing_metadata_item(folder, metadata)
        if missing_item["reasons"]:
            missing_items.append(missing_item)
        if download_cover_if_possible(folder, metadata, download_cover):
            result.cover_downloaded += 1
        else:
            result.cover_skipped += 1

        if progress_callback is not None:
            progress_callback("done", index, total_folders, folder.name, format_folder_status("完成（更新）" if should_write else "略過（已有資料）", missing_item["reasons"]))

    write_text(root / CATALOG_FILE_NAME, render_catalog(records))
    write_text(root / ACTRESSES_CATALOG_FILE_NAME, render_actresses_catalog(records))
    write_text(root / MISSING_METADATA_FILE_NAME, render_missing_metadata(missing_items))
    result.catalog_written = True
    result.actresses_catalog_written = True
    result.missing_metadata_written = True
    result.missing_metadata_items = missing_items
    result.total_records = len(records)
    return result


def load_gui_state(app_root: Path) -> dict[str, Any]:
    state_path = app_root / GUI_STATE_FILE
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_gui_state(app_root: Path, state: dict[str, Any]) -> None:
    state_path = app_root / GUI_STATE_FILE
    write_text(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def summarize_result(result: SyncResult, download_cover: bool = False, preview_delete: bool = False) -> str:
    lines = [
        f"根目錄: {result.root}",
        f"模式: {MODE_LABELS.get(result.mode, result.mode)}",
        f"整理根目錄單檔: {result.organized_root_files}",
        f"新增 info.md: {result.created}",
        f"更新 info.md: {result.updated}",
        f"略過資料夾: {result.skipped}",
        f"其中未下載完成而略過: {result.skipped_incomplete}",
        f"重新命名影音檔: {result.renamed_videos}",
        f"刪除無關檔案: {result.deleted_files}",
        f"成功抓到線上資料: {result.metadata_fetched}",
        f"抓取失敗或無結果: {result.metadata_failed}",
        f"catalog.md 已更新: {'yes' if result.catalog_written else 'no'}",
        f"actresses.md 已更新: {'yes' if result.actresses_catalog_written else 'no'}",
        f"missing-metadata.md 已更新: {'yes' if result.missing_metadata_written else 'no'}",
        f"缺資料目錄: {len(result.missing_metadata_items)}",
        f"總影片資料夾: {result.total_records}",
    ]
    if download_cover:
        lines.append(f"封面下載成功: {result.cover_downloaded}")
        lines.append(f"封面略過或失敗: {result.cover_skipped}")
    if preview_delete:
        lines.append(f"待刪檔案預覽: {len(result.pending_delete_paths)}")
        for path in result.pending_delete_paths[:SUMMARY_PREVIEW_LIMIT]:
            lines.append(f"- {path}")
        remaining = len(result.pending_delete_paths) - SUMMARY_PREVIEW_LIMIT
        if remaining > 0:
            lines.append(f"- ... 還有 {remaining} 個檔案")
    return "\n".join(lines)
