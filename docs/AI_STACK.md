# AI stack

Every model the application uses, what it does, why it was chosen and how it is run. Everything runs on the user's own
computer. Hardware this was developed and measured on: **RTX 4050 laptop GPU, 6.44 GB VRAM**.

| # | component | task | kind | where | runs on |
|---|---|---|---|---|---|
| 1 | **YOLO12n** (ultralytics) | detect a person and a phone in the webcam frame | pretrained CNN detector | `detection/detector.py`, `camera_thread.py` | GPU if available, else CPU; worker thread |
| 2 | **BART-large-CNN** (`facebook/bart-large-cnn`) | summarise text / PDFs | pretrained seq2seq | `assistant/summarizer.py` | GPU/CPU; `AIWorker` thread |
| 3 | **MarianMT** (`Helsinki-NLP/opus-mt-*` pair models) | translate between English, Arabic, French, German | pretrained seq2seq | `assistant/translator.py` | GPU/CPU; `AIWorker` thread |
| 4 | **Intent classifier** (own, ~1 MB) | understand a chat question about tasks / calendar / team | small PyTorch network, trained here | `assistant/intent_model.py`, `intents.py` | CPU, microseconds, main thread |
| 5 | **Qwen2.5-1.5B-Instruct** | answer general questions ("how do I build a CNN?") | pretrained LLM, fp16 | `llm/` | GPU (about 3.1 GB) or CPU fallback; worker thread |
| 6 | **BM25** (own, no library) | find the passages of the manager's documents that answer a question | classic ranking function | `knowledge/` | CPU, milliseconds, main thread |

## 1. YOLO12n -- presence and phone detection
* **Why:** it is small (about 5 MB), fast on a laptop GPU and the COCO classes already contain `person` (0) and
  `cell phone` (67). No training was needed.
* **How:** `CameraThread` reads frames (about 30 FPS cap), `Detector.detect()` returns two booleans and an annotated
  frame. Only the booleans reach `SessionState`; frames are shown in the preview and then dropped.
* **Weights:** `models/yolo12n.pt` (ultralytics downloads them there if missing).
* **Limit:** a phone held at an odd angle or a person turned away can be missed; the timers are therefore driven by
  several signals (keyboard idle, screen category), not the camera alone.

## 2. BART-large-CNN -- summaries
* **Why:** a well-known abstractive summariser that handles news-style prose and runs locally.
* **How:** the text is split into chunks of at most 1024 tokens (BART's limit), each chunk is summarised, the partial
  summaries are joined (`MAX_INPUT_TOKENS`, `MAX_SUMMARY_TOKENS`). PDFs are read with PyMuPDF (`assistant/extractors.py`).
* **First use:** the weights are downloaded from the Hugging Face hub if they are not cached yet.

## 3. MarianMT -- translation
* **Why:** one small model per language pair (hundreds of MB, not billions of parameters), good enough quality, offline.
* **How:** `DIRECT_MODELS` lists the pairs that exist on the hub; other pairs are translated in two legs through English
  (`Translator.model_names` returns the one or two models used). Loaded models are cached per pair.
* **First use:** downloads the pair's weights unless cached.

## 4. The intent classifier -- the *exact* part of the chat
* **What it is:** a fastText-style network (hashed word, bigram and character n-gram features plus concept-lexicon features
  -> `EmbeddingBag(32)` -> hidden 64 -> 20 intents), ~1 MB, trained on about 6,000 generated sentences in English and
  Arabic. Entities (task titles, employee names) are masked before classification; typos are repaired against the vocabulary.
* **Why own instead of an LLM:** questions like "who should I check in on?" must be answered with **exact numbers from SQL**
  and must obey **roles**. A classifier that only picks an intent, followed by ordinary code that reads the database, can
  neither invent a number nor leak a row. It is also instant and needs no GPU.
* **Honest accuracy:** 85.3 % on a fresh held-out set (109 questions), 87.6 % and 79.5 % on two older sets. Below a
  confidence of 0.40 the answer is "unknown".
* **Retrain:** `python -m assistant.train_intent` (writes `assistant/intent_model.pt` and `intent_report.txt`).

## 5. Qwen2.5-1.5B-Instruct -- general questions
* **Why this one:** the largest instruction-tuned model that fits next to YOLO in 6.44 GB without extra libraries
  (fp16 weights are 3.1 GB; Phi-3-mini would need about 7.6 GB). Apache-2.0 licence. Handles English and Arabic.
* **How:** `llm/model_manager.py` loads it lazily from `models/qwen2.5-1.5b-instruct` (`local_files_only=True`: it never
  touches the network), picks the GPU when at least 3.8 GB are free, otherwise bfloat16 on the CPU ("slow mode"), streams
  tokens with `TextIteratorStreamer`, stops within one token on `cancel()`, and frees the memory after 5 idle minutes.
* **What it is told** (`llm/prompts.py`): a fixed system instruction, up to six earlier question/answer pairs **that the
  model itself wrote** in this chat, the new question and -- if any -- document passages. Never tasks, calendar or team data.
* **Measured:** about 7-17 tokens/s on the GPU (varies), first token after 1-3 s, about 3.1 GB of VRAM, no UI freeze longer
  than 250 ms while it writes (about 0.5 s once while it loads).
* **Limits (important for the advisor):** a 1.5 B model writes standard PyTorch/Keras code well but can make small mistakes
  (a missing import, a wrong shape), is weak at multi-step reasoning, and can state wrong facts confidently. The prompt asks it
  to say when it is unsure; it cannot guarantee that.

## 6. BM25 retrieval -- the RAG layer
* **Why not embeddings:** no extra model, no extra download, runs in milliseconds, and is easy to explain.
* **How:** documents are cut at Markdown headings into passages of about 160 words (code blocks stay whole), terms are
  lower-cased, stemmed lightly and stop-words removed (English + Arabic). Okapi BM25 (`k1 = 1.5`, `b = 0.75`) ranks the
  passages; a passage is returned only if it covers at least half of the question's words (weighted by rarity), so an
  unanswered question returns **nothing** instead of the "least bad" passage.
* **Privacy:** the index an employee searches contains only the `everyone` documents (see [PRIVACY.md](PRIVACY.md)).
* **Limit:** it matches *words*, not meaning. A question that uses different words than the note ("prevent" vs "avoid")
  can miss; the answer then comes from the model without the document and carries no "Sources" line.
* **Citation:** the app (not the model) appends `Sources: file.md` after an answer that was given document passages.

## How the chat chooses (summary)

1. The engine classifies the question. A **data question** (tasks, deadlines, calendar, own focus time; for managers also the
   team) is answered by the engine from SQL.
2. Otherwise (unknown intent, a weak match, an unfamiliar topic word, a follow-up to a model answer) the question goes to the
   model, with document passages if the knowledge base has any for this user.
3. If the model is off, missing or fails, the engine's honest "not sure" -- or the quoted passages -- is shown instead.
