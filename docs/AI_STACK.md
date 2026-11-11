# AI stack

Every model the application uses, what it does, why it was chosen and how it is run. Models 1-4 run on the user's
own computer; the general-purpose language model (5) runs online, called by the company's server, and the document
search (6) runs on the server. Hardware this was developed and measured on: **RTX 4050 laptop GPU, 6.44 GB VRAM**.

| # | component | task | kind | where | runs on |
|---|---|---|---|---|---|
| 1 | **YOLO12n** (ultralytics) | detect a person and a phone in the webcam frame | pretrained CNN detector | `detection/detector.py`, `camera_thread.py` | GPU if available, else CPU; worker thread |
| 2 | **BART-large-CNN** (`facebook/bart-large-cnn`) | summarise text / PDFs | pretrained seq2seq | `assistant/summarizer.py` | GPU/CPU; `AIWorker` thread |
| 3 | **MarianMT** (`Helsinki-NLP/opus-mt-*` pair models) | translate between English, Arabic, French, German | pretrained seq2seq | `assistant/translator.py` | GPU/CPU; `AIWorker` thread |
| 4 | **Intent classifier** (own, ~1 MB) | understand a chat question about tasks / calendar / team | small PyTorch network, trained here | `assistant/intent_model.py`, `intents.py` | CPU, microseconds, main thread |
| 5 | **`openai/gpt-oss-120b` at Groq** | answer general and document questions ("how do I build a CNN?") | hosted LLM (Apache-2.0 weights) | `backend/app/services/`, `llm/` (client side) | online, through the service; streamed to the app |
| 6 | **BM25** (own, no library) | find the passages of the manager's documents that answer a question | classic ranking function | `knowledge/`, the service | server (local mode: the PC), milliseconds |

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
* **Weights:** a local copy in `models/hf/bart-large-cnn` (bundled in the installer; no internet needed).

## 3. MarianMT -- translation
* **Why:** one small model per language pair (hundreds of MB, not billions of parameters), good enough quality, offline.
* **How:** `DIRECT_MODELS` lists the pairs that exist on the hub; other pairs are translated in two legs through English
  (`Translator.model_names` returns the one or two models used). Loaded models are cached per pair.
* **Weights:** local copies of all 12 pairs in `models/hf/opus-mt-*` (bundled in the installer).

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

## 5. The online model -- general questions
* **Version 1** shipped Qwen2.5-1.5B-Instruct on the PC (3.1 GB of weights, about 3.1 GB of graphics memory, slow on
  computers without an NVIDIA GPU, and weak at multi-step reasoning). **Version 2** removed it: the installer is about
  3 GB smaller and every PC gets the same, much stronger model.
* **Why `openai/gpt-oss-120b` at Groq:** open weights (Apache-2.0), strong at code and explanations, very fast
  streaming, and Groq's terms do not use requests for training.
* **How:** the app sends the question to the company's server (`POST /ai/chat`, streamed). The server checks the
  company's daily token budget, builds the prompt -- a fixed instruction, the model's **own** earlier answers in this chat
  and, if any, document passages the asker may read -- and streams the answer back. The API key lives only on the server.
* **Never in the prompt:** tasks, calendars, team numbers or other people's data (tests check the prompt builder).
* **Switch off:** Settings -> AI assistant (or `OFFICE_LLM=0`); the chat then answers only from the user's data.
* **Limits:** the model can still be wrong or state wrong facts confidently; answers that used documents show their
  sources, and generated code should be read before use.

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

1. The engine classifies the question on the PC. A **data question** (tasks, deadlines, calendar, own focus time; for
   managers also the team) is answered by the engine from the user's data on the service -- never by the model.
2. Otherwise (unknown intent, a weak match, an unfamiliar topic word, a follow-up to a model answer) the question goes to the
   model, with document passages if the knowledge base has any for this user.
3. If the model is off, offline, over budget or fails, the engine's honest "not sure" -- or the quoted passages -- is shown
   instead, with a short note saying why.
