"""Self-test of the language model backend:  python -m llm.selftest

Needs the downloaded model.  Measures load time, speed and GPU memory, tests
Stop, history trimming, unloading, the CPU fallback path and that the Qt workers
deliver text without freezing the event loop.
"""

import os
import sys
import time

import sentencepiece  # noqa: F401  (must be imported before PyQt5 on this machine)
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import config
from llm.model_manager import LLMManager, ModelNotAvailable

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + label + ((" | " + str(detail)[:300].replace("\n", " / ")) if detail else ""))


SYSTEM = {"role": "system", "content": "You are a helpful assistant. Answer briefly."}


def gb():
    return torch.cuda.memory_allocated() / 1e9 if torch.cuda.is_available() else 0.0


def main():
    m = LLMManager()
    check("model files found", m.available() and m.status() == "not loaded")
    base = gb()
    t = time.time()
    device = m.load()
    check("loads (%s) in %.1f s" % (device, time.time() - t), m.loaded and device == ("cuda" if torch.cuda.is_available() else "cpu"))
    print("   VRAM used by the model: %.2f GB" % (gb() - base))
    check("model uses about 3 GB of VRAM", device != "cuda" or 2.5 < gb() - base < 4.0)

    started = time.time()
    first = None
    pieces = []
    for p in m.stream([SYSTEM, {"role": "user", "content": "What is a convolutional neural network? Two sentences."}], max_new_tokens=80):
        if first is None:
            first = time.time() - started
        pieces.append(p)
    text = "".join(pieces)
    total = time.time() - started
    tokens = len(m.tokenizer(text)["input_ids"])
    print("   first piece after %.2f s, %d tokens in %.1f s (%.1f tok/s)" % (first, tokens, total, tokens / max(total, 1e-6)))
    print("   reply:", text.replace("\n", " ")[:200])
    check("streams text in several pieces", len(pieces) > 5 and "neural" in text.lower() or "convolution" in text.lower())

    # --- stop ---------------------------------------------------------------------
    import threading
    count = []
    def go():
        for p in m.stream([SYSTEM, {"role": "user", "content": "Write a long essay about deep learning."}], max_new_tokens=400):
            count.append(p)
    th = threading.Thread(target=go); th.start()
    while len(count) < 6 and th.is_alive():
        time.sleep(0.02)
    t = time.time(); m.cancel(); th.join(10)
    check("Stop ends generation within a second", not th.is_alive() and time.time() - t < 1.0 and len(count) < 200, "%d pieces, %.2fs" % (len(count), time.time() - t))
    reply = m.ask([SYSTEM, {"role": "user", "content": "Say hello."}], max_new_tokens=20)
    check("works again right after a stop", bool(reply.strip()), reply)

    # --- chat memory / follow-up -------------------------------------------------------------
    history = [SYSTEM, {"role": "user", "content": "My favourite number is 42. Remember it."},
               {"role": "assistant", "content": "Okay, I will remember 42."},
               {"role": "user", "content": "What is my favourite number? Reply with the number only."}]
    reply = m.ask(history, max_new_tokens=10)
    check("follow-up uses earlier turns", "42" in reply, reply)

    # --- long history is trimmed, system prompt kept -------------------------------------------------
    long = [SYSTEM]
    for i in range(300):
        long += [{"role": "user", "content": "Filler question number %d about nothing in particular." % i},
                 {"role": "assistant", "content": "Filler answer number %d with a few more words." % i}]
    long.append({"role": "user", "content": "Say OK."})
    ids = m._build_inputs(long)["input_ids"]
    decoded = m.tokenizer.decode(ids[0])
    check("long history is trimmed to the limit", ids.shape[1] <= config.MAX_INPUT_TOKENS, ids.shape[1])
    check("...system prompt and newest question survive", "Answer briefly" in decoded and "Say OK." in decoded)
    check("a trimmed prompt still generates", bool(m.ask(long, max_new_tokens=8).strip()))

    # --- errors ------------------------------------------------------------------------------------------------
    try:
        LLMManager(model_dir=os.path.join(config.PROJECT_ROOT, "models", "nope")).load()
        check("missing model raises a clear error", False)
    except ModelNotAvailable as error:
        check("missing model raises a clear error", "not found" in str(error), error)

    # --- idle unload / reload --------------------------------------------------------------------------------------
    check("not unloaded while recently used", not m.unload_if_idle(seconds=60) and m.loaded)
    check("idle unload frees the model", m.unload_if_idle(seconds=0) and not m.loaded)
    check("VRAM is released after unload", gb() <= base + 0.05, "%.2f GB left" % gb())
    m.load()
    check("reloads after unload", bool(m.ask([SYSTEM, {"role": "user", "content": "Say hi."}], max_new_tokens=8).strip()))
    m.unload()

    # --- CPU fallback ---------------------------------------------------------------------------------------------------
    t = time.time()
    m.load(device="cpu")
    out = m.ask([SYSTEM, {"role": "user", "content": "Say hi."}], max_new_tokens=8)
    check("CPU fallback works (%.1f s incl. load)" % (time.time() - t), m.device == "cpu" and bool(out.strip()), out)
    m.unload()

    # --- Qt workers -------------------------------------------------------------------------------------------------------------
    from PyQt5.QtCore import QCoreApplication, QTimer
    from llm import workers
    from llm.model_manager import get_manager
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    state = {"ticks": 0, "pieces": [], "loaded": None, "done": None, "failed": None}
    def beat():
        now = time.monotonic()
        state["gap"] = max(state.get("gap", 0), now - state.get("last", now))
        state["last"] = now
        state["ticks"] += 1
    heartbeat = QTimer(); heartbeat.timeout.connect(beat); heartbeat.start(20)

    def wait(cond, timeout=60):
        end = time.time() + timeout
        while not cond() and time.time() < end:
            app.processEvents(); time.sleep(0.005)

    lw = workers.LoadWorker(); lw.loaded.connect(lambda d: state.__setitem__("loaded", d)); lw.start()
    wait(lambda: state["loaded"])
    check("LoadWorker loads without blocking the event loop", state["loaded"] and state["ticks"] > 20, "%s, %d ticks" % (state["loaded"], state["ticks"]))
    state["ticks"] = 0; state["gap"] = 0; state["last"] = time.monotonic()
    gw = workers.GenerateWorker([SYSTEM, {"role": "user", "content": "List three CNN layer types."}])
    gw.piece.connect(state["pieces"].append); gw.done.connect(lambda s: state.__setitem__("done", s)); gw.failed.connect(lambda e: state.__setitem__("failed", e))
    gw.start(); wait(lambda: state["done"] is not None or state["failed"])
    check("GenerateWorker streams text and finishes", state["done"] is False and len(state["pieces"]) > 5, state["failed"])
    print("   longest freeze of the event loop while writing: %.0f ms (%d ticks)" % (state["gap"] * 1000, state["ticks"]))
    check("the event loop never froze for more than 250 ms while it wrote", state["gap"] < 0.25, state["gap"])
    state.update(pieces=[], done=None)
    gw = workers.GenerateWorker([SYSTEM, {"role": "user", "content": "Write a very long essay about deep learning."}])
    gw.piece.connect(state["pieces"].append); gw.done.connect(lambda s: state.__setitem__("done", s)); gw.failed.connect(lambda e: state.__setitem__("failed", e))
    gw.start(); wait(lambda: len(state["pieces"]) >= 5)
    gw.stop(); wait(lambda: state["done"] is not None, 10)
    check("GenerateWorker.stop() ends it with stopped=True", state["done"] is True and len(state["pieces"]) < 150, len(state["pieces"]))
    get_manager().unload()
    check("no Qt/GPU leftovers: VRAM back to baseline", gb() <= base + 0.05, "%.2f GB" % gb())

    print("\nSUMMARY %d / %d passed" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
