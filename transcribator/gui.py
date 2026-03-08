"""
Desktop GUI for Transcribator: select files, choose output dir and model, run transcription.
Run: python -m transcribator.gui
"""
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .core import transcribe_file

# Models available in faster-whisper
MODELS = ("tiny", "base", "small", "medium", "large-v3")


def _run_transcription(
    files: list[Path],
    output_dir: Path | None,
    model_name: str,
    log_queue: queue.Queue[str],
) -> None:
    """Worker: transcribe each file, put messages into log_queue."""
    for i, path in enumerate(files, 1):
        path = path.resolve()
        if not path.exists():
            log_queue.put(f"[Ошибка] Файл не найден: {path}")
            continue
        if not path.is_file():
            log_queue.put(f"[Ошибка] Не файл: {path}")
            continue
        log_queue.put(f"[{i}/{len(files)}] Обработка: {path.name}")
        try:
            txt_path, json_path = transcribe_file(
                path,
                output_dir=output_dir,
                model_name=model_name,
                device="cpu",
                language="ru",
            )
            log_queue.put(f"  → Готово: {txt_path.name}, {json_path.name}")
        except FileNotFoundError as e:
            log_queue.put(f"  → Ошибка: {e}")
        except RuntimeError as e:
            log_queue.put(f"  → Ошибка: {e}")
        except Exception as e:
            log_queue.put(f"  → Ошибка: {e}")
    log_queue.put("[Готово] Все файлы обработаны.")


def run_gui() -> None:
    """Start the desktop GUI."""
    # Disable noisy lib loggers in GUI
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    root = tk.Tk()
    root.title("Transcribator — аудио/видео в текст")
    root.minsize(520, 420)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)

    # State
    file_list: list[str] = []
    log_queue: queue.Queue[str] = queue.Queue()
    is_running = False

    # --- File list ---
    frm_files = ttk.LabelFrame(root, text="Файлы для транскрибации")
    frm_files.grid(row=0, column=0, padx=10, pady=6, sticky="ew")
    frm_files.columnconfigure(0, weight=1)

    listbox = tk.Listbox(frm_files, height=4, selectmode=tk.EXTENDED)
    listbox.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
    frm_files.rowconfigure(0, weight=0)

    def add_files() -> None:
        paths = filedialog.askopenfilenames(
            title="Выберите аудио или видео",
            filetypes=[
                ("Аудио/видео", "*.mp3 *.mp4 *.wav *.m4a *.avi *.mkv *.mov *.webm *.ogg *.flac"),
                ("Все файлы", "*.*"),
            ],
        )
        for p in paths:
            if p and p not in file_list:
                file_list.append(p)
                listbox.insert(tk.END, Path(p).name)

    def remove_selected() -> None:
        sel = list(listbox.curselection())
        for i in reversed(sel):
            listbox.delete(i)
            file_list.pop(i)

    ttk.Button(frm_files, text="Добавить файлы…", command=add_files).grid(
        row=1, column=0, padx=4, pady=4
    )
    ttk.Button(frm_files, text="Удалить выбранные", command=remove_selected).grid(
        row=1, column=1, padx=4, pady=4
    )

    # --- Output dir & model ---
    frm_opts = ttk.Frame(root)
    frm_opts.grid(row=1, column=0, padx=10, pady=4, sticky="ew")
    frm_opts.columnconfigure(1, weight=1)

    ttk.Label(frm_opts, text="Папка для результатов (необязательно):").grid(
        row=0, column=0, sticky="w", padx=4, pady=2
    )
    out_dir_var = tk.StringVar(value="")

    def browse_out() -> None:
        d = filedialog.askdirectory(title="Куда сохранять .txt и .json")
        if d:
            out_dir_var.set(d)

    ent_out = ttk.Entry(frm_opts, textvariable=out_dir_var)
    ent_out.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=2)
    ttk.Button(frm_opts, text="Обзор…", command=browse_out).grid(row=1, column=2, padx=4, pady=2)

    ttk.Label(frm_opts, text="Модель:").grid(row=2, column=0, sticky="w", padx=4, pady=4)
    model_var = tk.StringVar(value="small")
    model_combo = ttk.Combobox(
        frm_opts, textvariable=model_var, values=MODELS, state="readonly", width=12
    )
    model_combo.grid(row=2, column=1, sticky="w", padx=4, pady=4)

    # --- Log ---
    frm_log = ttk.LabelFrame(root, text="Лог")
    frm_log.grid(row=2, column=0, padx=10, pady=6, sticky="nsew")
    frm_log.columnconfigure(0, weight=1)
    frm_log.rowconfigure(0, weight=1)

    log_text = scrolledtext.ScrolledText(frm_log, height=10, state=tk.DISABLED, wrap=tk.WORD)
    log_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

    def append_log(msg: str) -> None:
        log_text.configure(state=tk.NORMAL)
        log_text.insert(tk.END, msg + "\n")
        log_text.see(tk.END)
        log_text.configure(state=tk.DISABLED)

    def process_log_queue() -> None:
        nonlocal is_running
        while True:
            try:
                msg = log_queue.get_nowait()
                if msg == "_DONE_":
                    is_running = False
                    btn_start.config(state=tk.NORMAL)
                else:
                    append_log(msg)
            except queue.Empty:
                break
        root.after(200, process_log_queue)

    def start_transcription() -> None:
        nonlocal is_running
        if is_running:
            return
        if not file_list:
            messagebox.showwarning("Нет файлов", "Добавьте хотя бы один файл.")
            return
        out = out_dir_var.get().strip()
        output_dir = Path(out).resolve() if out else None
        if out and not output_dir.is_dir():
            messagebox.showerror("Ошибка", f"Папка не существует:\n{output_dir}")
            return
        model_name = model_var.get()
        if model_name not in MODELS:
            model_name = "small"
        is_running = True
        btn_start.config(state=tk.DISABLED)
        append_log("--- Запуск ---")

        def worker() -> None:
            _run_transcription(
                [Path(f) for f in file_list],
                output_dir,
                model_name,
                log_queue,
            )
            log_queue.put("_DONE_")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    btn_start = ttk.Button(root, text="Запустить транскрибацию", command=start_transcription)
    btn_start.grid(row=3, column=0, padx=10, pady=10)

    root.after(200, process_log_queue)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
