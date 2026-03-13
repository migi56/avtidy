# Changelog

All notable changes to this project will be documented in this file.

## [0.9.19] - 2026-03-13

### Changed
- Renamed the project, package, CLI/GUI entry points, GUI window title, and state file from `av_tidy` to `avtidy`.
- Updated documentation and commands to use `avtidy`.

## [0.9.18] - 2026-03-13

### Changed
- Renamed the project, package, GUI title, state file, and CLI/GUI entry points from `avgo` to `avtidy`.

## [0.9.17] - 2026-03-13

### Changed
- Cleanup now preserves `.srt` subtitle files instead of marking them for deletion.

## [0.9.16] - 2026-03-13

### Added
- Added detailed GitHub-ready README documentation.
- Added `.gitignore`, `requirements.txt`, `LICENSE`, and `CHANGELOG.md` for open source release.

### Changed
- `actresses.md` now prefers Japanese / kanji actress names and shows English names as aliases.
- README now documents CLI, GUI, sync modes, generated files, naming rules, and usage flow.

## [0.9.15] - 2026-03-13

### Changed
- GUI per-folder status now distinguishes `部分完成` from true `失敗` when only some metadata is missing.

## [0.9.14] - 2026-03-13

### Fixed
- Fixed missing `format_folder_status` helper causing GUI execution failure.

## [0.9.13] - 2026-03-13

### Added
- GUI output panel now shows per-folder processing results in real time.

## [0.9.12] - 2026-03-13

### Changed
- Removed completion popup window from GUI.

## [0.9.11] - 2026-03-13

### Fixed
- Fixed incorrect missing-metadata classification for folders with suffixes like `-UC`, `-C`, `(2)`, and compact suffixes.

## [0.9.10] - 2026-03-13

### Added
- Added `missing-metadata.md` report for incomplete or suspicious records.

## [0.9.9] - 2026-03-13

### Added
- Added AV-Wiki, AVWikiDB, and Jable as extra metadata fallback sources.

## [0.9.8] - 2026-03-13

### Changed
- Standardized compact suffix handling such as `mkmp-677ch` -> `MKMP-677-CH`.

## [0.9.7] - 2026-03-13

### Added
- Added support for folder names like `START-473 (2)`.

## [0.9.6] - 2026-03-13

### Added
- Added support for suffix-preserving code parsing such as `MIDA-101-C` and `MIDA-010-uncensored-HD`.

## [0.9.5] - 2026-03-13

### Added
- Skip folders containing `.bc*` files as incomplete downloads.

## [0.9.4] - 2026-03-13

### Added
- Added `actresses.md` root index grouped by actress.

## [0.9.3] - 2026-03-13

### Added
- Added release-date folder renaming in `YYMMDD-CODE` format.

## [0.9.2] - 2026-03-13

### Added
- Added Japanese / kanji metadata fallback and English alias retention.

## [0.9.1] - 2026-03-13

### Added
- Added root loose video file organization into per-code folders.

## [0.9.0] - 2026-03-12

### Added
- Initial public feature set with CLI, GUI, markdown metadata, root catalog generation, cover download, video renaming, cleanup preview, and delete preview dialog.
