from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from avgo import __version__
from avgo.core import (
    MODE_LABELS,
    MODE_NEW_ONLY,
    MODE_REBUILD_CATALOG,
    MODE_RESCAN_ALL,
    MODE_RESCAN_MISSING,
    SyncResult,
    load_gui_state,
    save_gui_state,
    summarize_result,
    sync_library,
)

APP_ROOT = Path(__file__).resolve().parent
GUI_MODES = [MODE_NEW_ONLY, MODE_RESCAN_MISSING, MODE_RESCAN_ALL, MODE_REBUILD_CATALOG]
PREVIEW_WINDOW_LIMIT = 500


class DeletePreviewDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, paths: list[str]) -> None:
        super().__init__(master)
        self.title("待刪檔案預覽")
        self.geometry("860x520")
        self.resizable(True, True)
        self.result = False
        self.paths = paths

        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.build_ui()

    def build_ui(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        summary = ttk.Label(
            frame,
            text=f"共有 {len(self.paths)} 個檔案將被刪除。請確認清單後再決定是否繼續。",
        )
        summary.grid(row=0, column=0, sticky=tk.W)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=1, column=0, sticky=tk.NSEW, pady=(12, 12))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame)
        self.listbox.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.listbox.configure(yscrollcommand=scrollbar.set)

        for path in self.paths[:PREVIEW_WINDOW_LIMIT]:
            self.listbox.insert(tk.END, path)
        remaining = len(self.paths) - PREVIEW_WINDOW_LIMIT
        if remaining > 0:
            self.listbox.insert(tk.END, f"... 還有 {remaining} 個檔案未顯示")

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, sticky=tk.E)
        ttk.Button(actions, text="複製清單", command=self.copy_paths).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="匯出 TXT", command=self.export_paths).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="取消", command=self.cancel).pack(side=tk.RIGHT)
        ttk.Button(actions, text="確認刪除", command=self.confirm).pack(side=tk.RIGHT, padx=(0, 8))

    def copy_paths(self) -> None:
        payload = "\n".join(self.paths)
        self.clipboard_clear()
        self.clipboard_append(payload)
        messagebox.showinfo("已複製", "待刪清單已複製到剪貼簿。", parent=self)

    def export_paths(self) -> None:
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="匯出待刪清單",
            defaultextension=".txt",
            filetypes=[("Text File", "*.txt"), ("All Files", "*.*")],
            initialfile="delete-preview.txt",
        )
        if not file_path:
            return
        Path(file_path).write_text("\n".join(self.paths) + "\n", encoding="utf-8")
        messagebox.showinfo("已匯出", f"待刪清單已匯出到:\n{file_path}", parent=self)

    def confirm(self) -> None:
        self.result = True
        self.destroy()

    def cancel(self) -> None:
        self.result = False
        self.destroy()


class AvgoApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"AVGO Catalog Tool v{__version__}")
        self.root.geometry("820x640")

        self.state = load_gui_state(APP_ROOT)
        last_mode = self.state.get("last_mode", MODE_NEW_ONLY)
        self.root_var = tk.StringVar(value=self.state.get("last_root", ""))
        self.mode_var = tk.StringVar(value=last_mode if last_mode in GUI_MODES else MODE_NEW_ONLY)
        self.download_cover_var = tk.BooleanVar(value=bool(self.state.get("download_cover", False)))
        self.preview_delete_var = tk.BooleanVar(value=bool(self.state.get("preview_delete", False)))
        self.status_var = tk.StringVar(value="選擇影片根目錄、模式與附加選項後即可開始。")

        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self.build_ui()

    def build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="根目錄").grid(row=0, column=0, sticky=tk.W, pady=(0, 12))
        ttk.Entry(frame, textvariable=self.root_var).grid(row=0, column=1, sticky=tk.EW, pady=(0, 12))
        ttk.Button(frame, text="選擇", command=self.choose_root).grid(row=0, column=2, padx=(12, 0), pady=(0, 12))

        options = ttk.LabelFrame(frame, text="執行模式", padding=12)
        options.grid(row=1, column=0, columnspan=3, sticky=tk.EW)
        for index, mode in enumerate(GUI_MODES):
            pady = (0, 0) if index == 0 else (8, 0)
            ttk.Radiobutton(options, text=MODE_LABELS[mode], value=mode, variable=self.mode_var).pack(anchor=tk.W, pady=pady)

        extras = ttk.LabelFrame(frame, text="附加選項", padding=12)
        extras.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(12, 0))
        ttk.Checkbutton(extras, text="可下載就下載封面", variable=self.download_cover_var).pack(anchor=tk.W)
        ttk.Checkbutton(extras, text="先預覽待刪檔案", variable=self.preview_delete_var).pack(anchor=tk.W, pady=(8, 0))

        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(12, 8))
        self.start_button = ttk.Button(actions, text="開始執行", command=self.run_sync)
        self.start_button.pack(side=tk.LEFT)

        status_frame = ttk.Frame(frame)
        status_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(0, 12))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=0, column=0, sticky=tk.W)
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))

        self.output = tk.Text(frame, wrap=tk.WORD, height=24)
        self.output.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW)
        self.output.configure(state=tk.DISABLED)

    def choose_root(self) -> None:
        current = self.root_var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(initialdir=current)
        if selected:
            self.root_var.set(selected)

    def clear_output(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.configure(state=tk.DISABLED)

    def append_output(self, message: str) -> None:
        self.output.configure(state=tk.NORMAL)
        if self.output.index("end-1c") != "1.0":
            self.output.insert(tk.END, "\n")
        self.output.insert(tk.END, message.rstrip() + "\n")
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)

    def confirm_preview_delete(self, paths: list[str]) -> bool:
        dialog = DeletePreviewDialog(self.root, paths)
        self.root.wait_window(dialog)
        return dialog.result

    def set_running(self, running: bool, message: str) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.status_var.set(message)
        if running:
            self.progress.start(10)
        else:
            self.progress.stop()

    def update_progress(self, current: int, total: int, folder_name: str) -> None:
        self.status_var.set(f"處理中 {current}/{total}: {folder_name}")

    def start_worker(self, root_path: Path, mode: str, download_cover: bool, preview_delete: bool) -> None:
        self.set_running(True, "正在準備掃描...")
        self.worker_thread = threading.Thread(
            target=self.worker_sync,
            args=(root_path, mode, download_cover, preview_delete),
            daemon=True,
        )
        self.worker_thread.start()
        self.root.after(100, self.poll_worker)

    def worker_sync(self, root_path: Path, mode: str, download_cover: bool, preview_delete: bool) -> None:
        try:
            result = sync_library(
                root_path,
                mode,
                download_cover=download_cover,
                preview_delete=preview_delete,
                progress_callback=lambda phase, current, total, folder_name, status: self.worker_queue.put(
                    ("progress", (phase, current, total, folder_name, status))
                ),
            )
            self.worker_queue.put(("result", (result, download_cover, preview_delete, root_path, mode)))
        except Exception as exc:  # noqa: BLE001
            self.worker_queue.put(("error", exc))

    def poll_worker(self) -> None:
        saw_terminal_event = False
        while True:
            try:
                kind, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                phase, current, total, folder_name, status = payload  # type: ignore[misc]
                if phase == "start":
                    self.update_progress(current, total, folder_name)
                elif phase == "done":
                    label = status or "完成"
                    self.append_output(f"[{current}/{total}] {folder_name} -> {label}")
                continue

            if kind == "error":
                self.worker_thread = None
                self.set_running(False, "執行失敗。")
                messagebox.showerror("執行失敗", str(payload))
                saw_terminal_event = True
                break

            result, download_cover, preview_delete, root_path, mode = payload  # type: ignore[misc]
            self.worker_thread = None
            self.handle_result(result, download_cover, preview_delete, root_path, mode)
            saw_terminal_event = True
            break

        if not saw_terminal_event and self.worker_thread is not None and self.worker_thread.is_alive():
            self.root.after(100, self.poll_worker)

    def handle_result(
        self,
        result: SyncResult,
        download_cover: bool,
        preview_delete: bool,
        root_path: Path,
        mode: str,
    ) -> None:
        save_gui_state(
            APP_ROOT,
            {
                "last_root": str(root_path),
                "last_mode": mode,
                "download_cover": download_cover,
                "preview_delete": preview_delete,
            },
        )
        self.append_output("=== 執行摘要 ===")
        self.append_output(summarize_result(result, download_cover=download_cover, preview_delete=preview_delete))

        if preview_delete and result.pending_delete_paths:
            self.set_running(False, f"預覽完成，共有 {len(result.pending_delete_paths)} 個待刪檔案。")
            confirmed = self.confirm_preview_delete(result.pending_delete_paths)
            if confirmed:
                self.start_worker(root_path, mode, download_cover, False)
                return
            messagebox.showinfo("已預覽", "本次只做預覽，尚未刪除任何檔案。")
            return

        self.set_running(False, f"同步完成，共處理 {result.total_records} 個資料夾。")

    def run_sync(self) -> None:
        raw_root = self.root_var.get().strip()
        if not raw_root:
            messagebox.showwarning("缺少根目錄", "請先選擇影片根目錄。")
            return

        root_path = Path(raw_root).expanduser().resolve()
        if not root_path.exists() or not root_path.is_dir():
            messagebox.showerror("根目錄不存在", f"找不到資料夾:\n{root_path}")
            return

        if self.worker_thread is not None and self.worker_thread.is_alive():
            messagebox.showinfo("執行中", "目前已有任務正在執行，請稍候。")
            return

        mode = self.mode_var.get() or MODE_NEW_ONLY
        download_cover = self.download_cover_var.get()
        preview_delete = self.preview_delete_var.get()
        self.clear_output()
        self.append_output(f"根目錄: {root_path}")
        self.append_output(f"模式: {MODE_LABELS.get(mode, mode)}")
        self.append_output("開始處理...")
        self.start_worker(root_path, mode, download_cover, preview_delete)


def main() -> int:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = AvgoApp(root)
    app.append_output("選擇影片根目錄、模式與附加選項後即可開始。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


