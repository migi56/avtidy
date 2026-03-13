# avtidy v0.9.19

avtidy 是一個用來整理本機 AV 影片目錄的工具，提供 CLI 與 GUI 兩種使用方式。

它會掃描你指定的根目錄，從資料夾名稱或單獨大檔案解析番號，盡量從多個網站抓取片名、女優、片商、發行日期與封面，然後自動整理檔案、建立 Markdown 索引，讓整個收藏更好找、更好維護。

## 功能總覽

- 掃描根目錄下的影片資料夾與單獨大檔案
- 支援 CLI 與 GUI
- GUI 會記住上一次開啟的根目錄
- 依番號查詢作品資料，優先保留日文 / 漢字標題與女優名
- 自動建立每個目錄的 `info.md`
- 自動重建根目錄索引 `catalog.md`
- 自動生成女優索引 `actresses.md`（女優名稱以漢字為主，英文名作為 Alias）
- 自動生成缺資料清單 `missing-metadata.md`
- 自動把資料夾改名成 `YYMMDD-番號` 格式
- 自動把大於 1GB 的影音檔重新命名成標準番號格式
- 可選擇下載封面
- 清理時會保留 `.srt` 字幕檔
- 可選擇先預覽待刪檔案，再決定是否刪除
- 執行中會即時顯示每個目錄的處理結果
- 若發現 `.bc*` 檔案，會視為未下載完成並略過該資料夾

## 命名與整理規則

### 1. 番號解析

程式會先從資料夾名解析出主番號，再保留原本尾碼。

支援像這些常見格式：

- `START-473`
- `START-473 (2)`
- `MIDA-101-C`
- `MIDA-010-uncensored-HD`
- `MIDV-946-UC`
- `mkmp-677ch`

解析邏輯範例：

- `START-473 (2)` -> 查詢用 `START-473`，尾碼保留 ` (2)`
- `MIDA-101-C` -> 查詢用 `MIDA-101`，尾碼保留 `-C`
- `MIDA-010-uncensored-HD` -> 查詢用 `MIDA-010`，尾碼保留 `-uncensored-HD`
- `mkmp-677ch` -> 查詢用 `MKMP-677`，尾碼標準化為 `-CH`

### 2. 資料夾重新命名

如果成功抓到發行日期，資料夾會自動改成：

```text
YYMMDD-番號
```

例如：

```text
260311-START-473
```

若原本有尾碼，會保留在後面：

```text
260311-START-473 (2)
260311-MIDA-101-C
260311-MIDA-010-uncensored-HD
260311-MKMP-677-CH
```

### 3. 大型影音檔重新命名

只會處理大於 1GB 的影音檔。

- 如果目錄中只有 1 個大檔，會改成：`番號.ext`
- 如果有多個大檔，會依排序改成：`番號-1.ext`、`番號-2.ext`

例如：

```text
START-511.mp4
START-511-1.mp4
START-511-2.mkv
```

如果原始檔名尾碼有 `a/b`、`1/2`、`v1/v2` 這類資訊，程式會盡量依原順序排列。

### 4. 清理時保留的檔案

清理無關檔案時，程式會保留：

- `info.md`
- 封面圖片
- `.srt` 字幕檔
- 整理後的大型影音檔

如果有啟用預覽模式，這些保留檔案不會出現在待刪清單中。

### 5. 根目錄單獨大檔整理

如果根目錄下直接有單獨影音檔，且檔案大於 1GB，例如：

```text
D:\AV\MIRD-267.mp4
```

程式會先自動整理成：

```text
D:\AV\MIRD-267\MIRD-267.mp4
```

再以這個新資料夾繼續後續流程。

### 6. 未完成下載略過

如果資料夾中有 `.bc*` 檔案，代表還在下載中，整個資料夾會直接略過，不做以下操作：

- 不抓資料
- 不建立或更新 `info.md`
- 不改資料夾名
- 不改影片名
- 不清理檔案

## 資料來源

目前會依序嘗試以下來源：

1. `javdatabase`
2. `AV-Wiki`
3. `AVWikiDB`
4. `Jable`

用途大致如下：

- `javdatabase`：基本資料、片商、部分日期、封面
- `AV-Wiki`：補發行日期、補日文 / 漢字資料
- `AVWikiDB`：可用時補結構化資訊
- `Jable`：補日文 / 漢字標題與女優名

說明：

- 標題與女優名會優先用日文 / 漢字
- 英文標題與英文女優別名會保留在 `extra` 欄位
- 部分來源可能受 Cloudflare、網站改版、地區或年齡限制影響
- 因為來源是公開網站，所以不是每一片都保證能抓全

## 執行模式

### `new_only`

預設模式。

- 只處理沒有 `info.md` 的新資料夾
- 已有 `info.md` 的目錄會略過
- 最後仍會重建根目錄索引

### `rescan_missing`

- 只重新抓缺關鍵欄位的既有資料
- 適合補標題、女優、發行日期

### `rescan_all`

- 所有資料夾全部重跑
- 適合來源更新、規則更新後重新整理

### `rebuild_catalog`

- 不重抓網路資料
- 只重建根目錄索引檔

## 系統需求

- Windows
- Python 3.11 以上
- 網路連線
- `requests`

安裝依賴：

```powershell
pip install requests
```

## 快速開始

### 啟動 CLI

查看版本：

```powershell
python .\avtidy_cli.py --version
```

預設只處理新資料夾：

```powershell
python .\avtidy_cli.py "D:\AV"
```

全部重跑：

```powershell
python .\avtidy_cli.py "D:\AV" --rescan-all
```

只補缺欄位：

```powershell
python .\avtidy_cli.py "D:\AV" --rescan-missing
```

只重建索引：

```powershell
python .\avtidy_cli.py "D:\AV" --rebuild-catalog
```

下載封面：

```powershell
python .\avtidy_cli.py "D:\AV" --rescan-all --download-cover
```

先預覽待刪檔案：

```powershell
python .\avtidy_cli.py "D:\AV" --preview-delete
```

### 啟動 GUI

```powershell
python .\avtidy_gui.py
```

GUI 中可以：

- 選擇根目錄
- 切換執行模式
- 勾選是否下載封面
- 勾選是否先預覽待刪檔案
- 即時查看目前處理進度
- 在下方輸出框查看每個目錄的結果

## CLI 參數說明

```text
python .\avtidy_cli.py <root_path> [options]
```

常用參數：

- `--rescan-missing`：只補缺欄位
- `--rescan-all`：全部重跑
- `--rebuild-catalog`：只重建索引
- `--download-cover`：可下載到封面時一併下載
- `--preview-delete`：只預覽待刪檔案，不真的刪除
- `--version`：顯示版本

## 產出檔案說明

同步完成後，根目錄通常會有這些檔案：

### `catalog.md`

根目錄總索引，列出所有作品，方便總覽。

包含：

- 番號
- 標題
- 女優
- 片商
- 日期
- 狀態
- 資料夾連結

### `actresses.md`

以女優為主的索引檔。

包含：

- 女優名稱
- 片數統計
- 英文別名（如果有）
- 該女優在目前根目錄下的所有作品

### `missing-metadata.md`

列出目前資料不完整或疑似異常的目錄。

可能包含：

- 缺標題
- 缺女優
- 缺發行日期
- 疑似番號異常

## `info.md` 格式

每個影片資料夾內會生成一份 `info.md`，作為單片主資料。

範例：

```md
---
code: START-511
title: 日文標題
actresses:
  - 女優A
studio: SOD Create
release_date: 2026-03-03
path: ./260303-START-511
status: pending
created_at: 2026-03-13T00:00:00+08:00
updated_at: 2026-03-13T00:00:00+08:00
extra:
  source: javdatabase
  source_id: START-511
  source_url: https://www.javdatabase.com/...
  source_url_ja: https://av-wiki.net/...
  cover_url: https://...
  title_english: English Title
  actress_aliases:
    女優A: English Name
---

# Notes
```

欄位說明：

- `code`：主番號
- `title`：作品標題，優先使用日文 / 漢字
- `actresses`：女優列表，優先使用日文 / 漢字
- `studio`：片商
- `release_date`：發行日期
- `path`：目前資料夾相對路徑
- `status`：同步狀態
- `created_at` / `updated_at`：建立與更新時間
- `extra`：來源網址、英文標題、封面網址等延伸資訊

## GUI 顯示結果說明

GUI 下方輸出框會即時顯示每個目錄的處理結果，例如：

- `完成（新增）`
- `完成（更新）`
- `完成（重建索引）`
- `略過（已有資料）`
- `略過（下載未完成）`
- `部分完成（缺女優）`
- `部分完成（缺發行日期）`
- `失敗（缺標題、缺女優、缺發行日期）`

建議理解方式：

- `完成`：資料完整或主要流程已成功執行
- `部分完成`：有抓到作品，但仍缺部分欄位
- `略過`：因模式或下載狀態而未處理
- `失敗`：幾乎查無資料，或關鍵欄位全部缺失

## 建議使用流程

### 日常整理

1. 平常新增新片時，先跑預設模式 `new_only`
2. 想補齊舊資料時，跑 `--rescan-missing`
3. 來源規則更新或大量重整時，跑 `--rescan-all`
4. 真要清檔前，先用 `--preview-delete` 或 GUI 預覽確認

### 新增大量資料時

1. 先把根目錄整理好
2. 執行 GUI 或 CLI 預設模式
3. 先看 `missing-metadata.md`
4. 再決定是否用 `--rescan-all` 重跑

## 專案結構

```text
avtidy/
  avtidy/
    __init__.py
    core.py
    fetcher.py
  avtidy_cli.py
  avtidy_gui.py
  README.md
```

主要檔案用途：

- `avtidy/core.py`：掃描、改名、輸出索引、檔案整理
- `avtidy/fetcher.py`：多來源查詢與資料整合
- `avtidy_cli.py`：CLI 入口
- `avtidy_gui.py`：GUI 入口

## 注意事項

- 這是本機整理工具，不保證所有網站長期穩定可抓
- 來源網站若改版，可能需要更新解析規則
- 某些作品可能抓得到標題與日期，但抓不到女優，這會標示為 `部分完成`
- 預覽刪除模式建議先使用，尤其是第一次整理大資料夾時
- 如果你更新了命名規則或資料來源，建議重新跑一次 `--rescan-all`

## 開源建議

如果你要放上 GitHub，建議再補這幾個檔案：

- `LICENSE`
- `.gitignore`
- `requirements.txt`
- `CHANGELOG.md`

如果你要，我下一步可以直接幫你把這四個檔也一起補齊。
