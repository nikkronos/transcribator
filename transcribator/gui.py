"""
Desktop GUI for Transcribator: select files, choose output dir and model, run transcription.
Run: python -m transcribator.gui
"""
import gc
import logging
import os
import queue
import threading
import time
import traceback
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from faster_whisper import WhisperModel

from .core import transcribe_file

# Models available in faster-whisper
MODELS = ("tiny", "base", "small", "medium", "large-v3")
DEVICE_MODES = ("auto", "cuda", "cpu")


@dataclass
class ProgressEvent:
    file_index: int
    file_count: int
    file_name: str
    progress_percent: float | None
    eta_seconds: float | None


@dataclass
class WorkerResult:
    success: bool
    error_message: str | None = None


def _gui_crash_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "Transcribator"
    d.mkdir(parents=True, exist_ok=True)
    return d / "gui_crash.log"


def _format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "ETA: —"
    seconds_int = max(0, int(seconds))
    mins, secs = divmod(seconds_int, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"ETA: ~{hours:02d}:{mins:02d}:{secs:02d}"
    return f"ETA: ~{mins:02d}:{secs:02d}"


def _is_cuda_error(error: Exception) -> bool:
    text = str(error).lower()
    return "cuda" in text or "cublas" in text or "cudnn" in text


def _cuda_preflight(model_name: str) -> tuple[bool, str | None]:
    """
    Validate that CUDA can initialize model loading.
    Returns (is_available, optional_reason).
    """
    probe: WhisperModel | None = None
    try:
        probe = WhisperModel(model_name, device="cuda", compute_type="int8")
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        if probe is not None:
            try:
                del probe
            except Exception:
                pass
            gc.collect()


def _run_transcription(
    files: list[Path],
    output_dir: Path | None,
    model_name: str,
    device_mode: str,
    log_queue: queue.Queue[str | ProgressEvent],
) -> None:
    """Worker: transcribe each file, put messages into log_queue."""
    use_gpu = False
    if device_mode == "cpu":
        log_queue.put("Режим устройства: CPU (выбран вручную).")
    elif device_mode == "cuda":
        use_gpu = True
        log_queue.put("Режим устройства: GPU (выбран вручную).")
    else:
        ok, reason = _cuda_preflight(model_name)
        use_gpu = ok
        if ok:
            log_queue.put("Режим устройства: AUTO -> GPU.")
        else:
            short_reason = (reason or "неизвестная ошибка").strip()
            log_queue.put(f"Режим устройства: AUTO -> CPU (CUDA недоступна: {short_reason}).")

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
            selected_device = "cuda" if use_gpu else "cpu"

            def on_progress(percent: float | None, eta_seconds: float | None) -> None:
                log_queue.put(
                    ProgressEvent(
                        file_index=i,
                        file_count=len(files),
                        file_name=path.name,
                        progress_percent=percent,
                        eta_seconds=eta_seconds,
                    )
                )

            txt_path, json_path = transcribe_file(
                path,
                output_dir=output_dir,
                model_name=model_name,
                device=selected_device,
                language="ru",
                progress_callback=on_progress,
            )
            device_label = "GPU" if selected_device == "cuda" else "CPU"
            log_queue.put(f"  → Готово ({device_label}): {txt_path.name}, {json_path.name}")
        except RuntimeError as e:
            if use_gpu and device_mode == "auto" and _is_cuda_error(e):
                log_queue.put("  → CUDA ошибка, переключаюсь на CPU для этого файла…")
                try:
                    txt_path, json_path = transcribe_file(
                        path,
                        output_dir=output_dir,
                        model_name=model_name,
                        device="cpu",
                        language="ru",
                        progress_callback=on_progress,
                    )
                    log_queue.put(f"  → Готово (CPU): {txt_path.name}, {json_path.name}")
                except Exception as cpu_error:
                    log_queue.put(f"  → Ошибка (CPU): {cpu_error}")
            else:
                log_queue.put(f"  → Ошибка: {e}")
        except Exception as e:
            log_queue.put(f"  → Ошибка: {e}")
    log_queue.put("[Готово] Все файлы обработаны.")
    log_queue.put(WorkerResult(success=True))


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

    _orig_report_cb = getattr(root, "report_callback_exception", None)

    def report_callback_exception(exc, val, tb) -> None:  # type: ignore[no-untyped-def]
        text = "".join(traceback.format_exception(exc, val, tb))
        logging.error("Tk callback exception\n%s", text)
        try:
            with _gui_crash_log_path().open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        if callable(_orig_report_cb):
            try:
                _orig_report_cb(exc, val, tb)
            except Exception:
                pass

    root.report_callback_exception = report_callback_exception  # type: ignore[method-assign]

    # State
    file_list: list[str] = []
    log_queue: queue.Queue[str | ProgressEvent | WorkerResult] = queue.Queue()
    is_running = False
    worker_thread: threading.Thread | None = None
    current_file_name = ""
    last_progress_update = 0.0
    last_heartbeat_log = 0.0

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

    ttk.Label(frm_opts, text="Устройство:").grid(row=3, column=0, sticky="w", padx=4, pady=4)
    device_var = tk.StringVar(value="auto")
    device_combo = ttk.Combobox(
        frm_opts, textvariable=device_var, values=DEVICE_MODES, state="readonly", width=12
    )
    device_combo.grid(row=3, column=1, sticky="w", padx=4, pady=4)

    # --- Log ---
    frm_log = ttk.LabelFrame(root, text="Лог")
    frm_log.grid(row=2, column=0, padx=10, pady=6, sticky="nsew")
    frm_log.columnconfigure(0, weight=1)
    frm_log.rowconfigure(2, weight=1)

    progress_frame = ttk.Frame(frm_log)
    progress_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
    progress_frame.columnconfigure(0, weight=1)

    lbl_current = ttk.Label(progress_frame, text="Текущий файл: —")
    lbl_current.grid(row=0, column=0, sticky="w")
    lbl_current_eta = ttk.Label(progress_frame, text="ETA: —")
    lbl_current_eta.grid(row=0, column=1, sticky="e")

    progress_current = ttk.Progressbar(progress_frame, mode="indeterminate", maximum=100)
    progress_current.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))

    lbl_overall = ttk.Label(progress_frame, text="Очередь: 0/0")
    lbl_overall.grid(row=2, column=0, sticky="w")
    lbl_overall_pct = ttk.Label(progress_frame, text="0%")
    lbl_overall_pct.grid(row=2, column=1, sticky="e")

    progress_overall = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
    progress_overall.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 6))

    log_text = scrolledtext.ScrolledText(frm_log, height=10, state=tk.DISABLED, wrap=tk.WORD)
    log_text.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)

    def append_log(msg: str) -> None:
        log_text.configure(state=tk.NORMAL)
        log_text.insert(tk.END, msg + "\n")
        log_text.see(tk.END)
        log_text.configure(state=tk.DISABLED)

    def process_log_queue() -> None:
        nonlocal is_running, current_file_name, last_progress_update, worker_thread
        try:
            while True:
                try:
                    msg = log_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(msg, ProgressEvent):
                    last_progress_update = time.monotonic()
                    current_name = msg.file_name
                    current_file_name = current_name
                    if msg.progress_percent is None:
                        lbl_current.config(text=f"Текущий файл: {current_name} (обработка)")
                        lbl_current_eta.config(text="ETA: вычисляю…")
                        if str(progress_current.cget("mode")) != "indeterminate":
                            progress_current.configure(mode="indeterminate")
                        progress_current.start(10)
                        current_fraction = 0.0
                    else:
                        if str(progress_current.cget("mode")) != "determinate":
                            try:
                                progress_current.stop()
                            except tk.TclError:
                                pass
                            progress_current.configure(mode="determinate")
                        progress_current["value"] = msg.progress_percent
                        lbl_current.config(
                            text=f"Текущий файл: {current_name} ({msg.progress_percent:.1f}%)"
                        )
                        lbl_current_eta.config(text=_format_eta(msg.eta_seconds))
                        current_fraction = max(0.0, min(1.0, msg.progress_percent / 100.0))

                    total_files = max(1, msg.file_count)
                    completed_before_current = max(0, msg.file_index - 1)
                    overall_fraction = (completed_before_current + current_fraction) / total_files
                    overall_percent = overall_fraction * 100.0
                    progress_overall["value"] = overall_percent
                    lbl_overall.config(text=f"Очередь: {msg.file_index}/{msg.file_count}")
                    lbl_overall_pct.config(text=f"{overall_percent:.1f}%")
                elif isinstance(msg, WorkerResult):
                    is_running = False
                    thr = worker_thread
                    worker_thread = None
                    if thr is not None and thr.is_alive():
                        thr.join(timeout=120.0)
                    btn_start.config(state=tk.NORMAL)
                    try:
                        if str(progress_current.cget("mode")) == "indeterminate":
                            progress_current.stop()
                    except tk.TclError:
                        pass
                    progress_current.configure(mode="determinate")
                    progress_current["value"] = 100
                    lbl_current_eta.config(text="ETA: ~00:00")
                    progress_overall["value"] = 100
                    lbl_overall_pct.config(text="100.0%")
                    if not msg.success and msg.error_message:
                        append_log(f"[Ошибка] {msg.error_message}")
                    # After worker thread exits, nudge GC on the Tk main thread (Windows/pythonw).
                    root.after(250, gc.collect)
                elif msg == "_DONE_":
                    pass
                else:
                    append_log(msg)
        except Exception:
            logging.exception("Ошибка обработки очереди лога GUI")
            try:
                with _gui_crash_log_path().open("a", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except OSError:
                pass
            try:
                append_log(
                    f"[Ошибка интерфейса] подробности: {_gui_crash_log_path()}"
                )
            except Exception:
                pass
        root.after(200, process_log_queue)

    def heartbeat() -> None:
        nonlocal last_heartbeat_log
        if is_running and current_file_name and last_progress_update > 0:
            idle_seconds = int(time.monotonic() - last_progress_update)
            if idle_seconds >= 15:
                lbl_current.config(
                    text=f"Текущий файл: {current_file_name} (обработка, {idle_seconds}с без обновления)"
                )
                lbl_current_eta.config(text="ETA: пересчитываю…")
                now = time.monotonic()
                if now - last_heartbeat_log >= 30:
                    append_log(f"  → Обработка продолжается… {idle_seconds}с без нового сегмента.")
                    last_heartbeat_log = now
        root.after(1000, heartbeat)

    def start_transcription() -> None:
        nonlocal is_running, current_file_name, last_progress_update, last_heartbeat_log, worker_thread
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
        selected_device_mode = device_var.get()
        if selected_device_mode not in DEVICE_MODES:
            selected_device_mode = "auto"
        is_running = True
        current_file_name = ""
        last_progress_update = time.monotonic()
        last_heartbeat_log = 0.0
        btn_start.config(state=tk.DISABLED)
        append_log("--- Запуск ---")
        try:
            if str(progress_current.cget("mode")) == "indeterminate":
                progress_current.stop()
        except tk.TclError:
            pass
        progress_current.configure(mode="determinate")
        progress_current["value"] = 0
        progress_overall["value"] = 0
        lbl_current.config(text="Текущий файл: —")
        lbl_current_eta.config(text="ETA: —")
        lbl_overall.config(text=f"Очередь: 0/{len(file_list)}")
        lbl_overall_pct.config(text="0.0%")

        def worker() -> None:
            try:
                _run_transcription(
                    [Path(f) for f in file_list],
                    output_dir,
                    model_name,
                    selected_device_mode,
                    log_queue,
                )
            except Exception as e:
                log_queue.put(f"[Критическая ошибка] {e}")
                log_queue.put(WorkerResult(success=False, error_message=str(e)))
            finally:
                gc.collect()

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()

    btn_start = ttk.Button(root, text="Запустить транскрибацию", command=start_transcription)
    btn_start.grid(row=3, column=0, padx=10, pady=10)

    root.after(200, process_log_queue)
    root.after(1000, heartbeat)
    try:
        root.mainloop()
    except Exception:
        logging.exception("Критическая ошибка главного цикла GUI")
        try:
            with _gui_crash_log_path().open("a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except OSError:
            pass
        raise


def main() -> None:
    """Entry point with crash logging (pythonw-friendly)."""
    try:
        run_gui()
    except Exception:
        logging.exception("Необработанная ошибка GUI")
        try:
            with _gui_crash_log_path().open("a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
