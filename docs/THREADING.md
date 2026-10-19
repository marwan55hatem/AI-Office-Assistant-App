# Threading model

Qt widgets and the SQLite connection may only be used from **one thread: the Qt main (GUI) thread**. Everything slow runs
in a worker, and a worker talks to the rest of the program **only through signals** carrying plain data (bool, str, int,
numpy frames, dicts).

## Who runs where

| name | kind | file | does | emits |
|---|---|---|---|---|
| *main thread* | Qt event loop | `main.py` | all widgets, **all database access**, the chat engine, BM25 search, intent classifier | -- |
| `CameraThread` | `QThread` | `detection/camera_thread.py` | opens the webcam, loads YOLO12n, loops at about 30 FPS | `frame_ready(frame)`, `detection_update(person, phone)`, `error(str)` |
| `ScreenThread` | `QThread` | `detection/screen_thread.py` | every 2 s reads the focused window title and the keyboard/mouse idle time | `screen_update(title, category, whatsapp_elapsed)`, `idle_update(is_idle, seconds)` |
| `AIWorker` | `QThread` | `assistant/ai_worker.py` | runs one slow call (`Summarizer.summarize`, `Translator.translate`) | `finished_ok(str)`, `failed(str)` |
| `LoadWorker` | `QThread` | `llm/workers.py` | loads the language model (about 5-20 s) | `loaded(device)`, `failed(str)` |
| `GenerateWorker` | `QThread` | `llm/workers.py` | writes one model answer, token by token | `piece(str)`, `done(stopped)`, `failed(str)` |
| *generation thread* | `threading.Thread` | `llm/model_manager.py` | inside `LLMManager.stream`: runs `model.generate` while the `GenerateWorker` reads the streamer | (feeds a `TextIteratorStreamer`) |
| QTimers | main thread | several | 1 s session tick; typing / "thinking" animation; badge and idle-unload checks; notifier checks; 30 s page refresh | -- |

## The rules

1. **Never touch a widget or the database from a worker.** A worker receives its inputs in the constructor
   (`GenerateWorker` copies the message list) and reports results by signal. `tests/test_ui_smoke.py` runs the chat screen
   with a fake worker to show the screen only depends on those signals.
2. **The reply is computed on the main thread, then shown.** For data questions `LocalBackend.stream_reply` reads the
   database and the engine *immediately* (microseconds) and returns a plain iterator; the chat screen "types" it with a
   timer. No worker is needed, so nothing can outlive the screen. Only the language model needs a thread.
3. **Do not block the GUI thread.** The model is loaded in `LoadWorker`; the first CUDA initialisation can still hold the
   GIL for about 0.5 s once (measured), writing never stalls the event loop for more than 250 ms.
4. **Never destroy a running `QThread`.** Screens keep a reference, `stop()` it, `wait()` with a timeout, and let
   `deleteLater` run only after `finished` (`SessionPage` when a session ends; `AIChatScreen` connects
   `finished -> deleteLater` for its model workers).
5. **Stop must be cheap and safe.** `CameraThread.stop()` / `ScreenThread.stop()` clear a flag the loop checks;
   `GenerateWorker.stop()` sets a `threading.Event` that a `StoppingCriteria` reads, so generation ends within one token.
   A late signal from a stopped worker is ignored: the screen forgets the worker (`self._worker = None`) and every handler
   compares `worker is self._worker` first.
6. **One model, one lock.** `LLMManager` owns a `threading.Lock` that is held for the whole of a `stream()` call, so two
   answers can never run at once and the idle unload (`unload_if_idle`) refuses to run while a lock is held.
7. **Failures cross the boundary as signals, not exceptions.** Workers catch `Exception` and emit `failed(message)`; the
   chat screen then shows the engine's own answer instead of an error.
8. **Shared state is read-only or immutable.** Class-level caches (`Translator._cache`, the BM25 index per audience) are
   filled from one thread at a time; `SessionState` is only mutated by the main thread (signals are delivered there).

## The session timers in detail

`EmployeeScreen` owns a `SessionState`. Camera and screen signals arrive on the main thread (queued connections) and set
fields; a 1 s `QTimer` calls `tick()`, which adds one second to exactly one of the three counters. Writing to the database
happens only in the main thread (`log_event` on a state *change*, `end_session` when the session stops).

## Known limits

* `sqlite3.connect(..., check_same_thread=False)` is used, but nothing relies on it: the connection is single-threaded by
  convention (rule 1). If a worker ever needed the database it should open its own connection.
* The first `import torch` costs about 2 s; it happens lazily on the first AI action.
