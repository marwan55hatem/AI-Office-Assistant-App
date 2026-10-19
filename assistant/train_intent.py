"""Train the assistant's intent classifier and report how good it is.

Run from the project folder::

    python assistant/train_intent.py

It generates the training sentences from ``intents.BANK``, trains for a few
seconds on the CPU, writes ``assistant/intent_model.pt`` and measures accuracy on
``intents.HELD_OUT`` -- questions worded differently from anything it trained on.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assistant import intent_model  # noqa: E402
from assistant.entities import autocorrect, mask_entities  # noqa: E402
from assistant.intents import (  # noqa: E402
    BANK, FRESH3_PEOPLE, FRESH3_TASKS, FRESH_PEOPLE, FRESH_TASKS, HELD_OUT, HELD_OUT_2, HELD_OUT_3, INTENTS,
    generate_training_data,
)


DEV_PEOPLE = ["omar", "sara"]
DEV_TASKS = ["budget review", "website redesign", "flutter app", "contract review",
             "client email", "presentation", "report"]


def evaluate(classifier, test_sets, people=(), tasks=(), min_confidence=intent_model.MIN_CONFIDENCE):
    """Accuracy on ``{intent: [sentences]}``; returns ``(accuracy, per_intent, mistakes)``.

    Names are masked first, exactly as the answer engine does at run time.
    """
    correct = total = 0
    per_intent, mistakes = {}, []
    for intent, sentences in test_sets.items():
        hits = 0
        for sentence in sentences:
            guess, confidence = classifier.predict(autocorrect(mask_entities(sentence, people, tasks)), min_confidence)
            total += 1
            if guess == intent:
                hits += 1
                correct += 1
            else:
                mistakes.append((sentence, intent, guess, confidence))
        per_intent[intent] = (hits, len(sentences))
    return correct / max(1, total), per_intent, mistakes


def main():
    """Train the intent classifier and write the accuracy report."""
    samples = generate_training_data()
    print("training sentences : %d  (%d intents, %d example phrases)"
          % (len(samples), len(INTENTS), sum(len(v) for v in BANK.values())))

    started = time.time()
    classifier = intent_model.train(samples, INTENTS)
    seconds = time.time() - started
    size = intent_model.save(classifier)
    print("trained in %.1f s, saved %s (%.0f KB)" % (seconds, intent_model.MODEL_PATH, size / 1024))

    train_acc = sum(classifier.predict(text)[0] == intent for text, intent in samples[:1500]) / 1500
    dev_acc, dev_per, dev_mistakes = evaluate(classifier, HELD_OUT, DEV_PEOPLE, DEV_TASKS)
    acc, per_intent, mistakes = evaluate(classifier, HELD_OUT_2, FRESH_PEOPLE, FRESH_TASKS)
    n_dev = sum(total for _h, total in dev_per.values())
    n = sum(total for _h, total in per_intent.values())
    print("\naccuracy on training sentences (sample)        : %.1f %%" % (100 * train_acc))
    print("accuracy on test set 1 (used while tuning)     : %.1f %%  (%d questions)" % (100 * dev_acc, n_dev))
    print("accuracy on test set 2 (fresh, never tuned on) : %.1f %%  (%d questions)  <- honest figure" % (100 * acc, n))
    print("\nper intent (test set 2):")
    for intent in INTENTS:
        hits, total = per_intent.get(intent, (0, 0))
        if not total:
            continue
        print("  %-18s %d/%d" % (intent, hits, total))
    if mistakes:
        print("\nmistakes on test set 2:")
        for sentence, wanted, guess, confidence in mistakes:
            print("  %r\n      wanted %-16s got %-16s (%.2f)" % (sentence, wanted, guess, confidence))
    acc3, per3, mistakes3 = evaluate(classifier, HELD_OUT_3, FRESH3_PEOPLE, FRESH3_TASKS)
    n3 = sum(total for _h, total in per3.values())
    print("\naccuracy on test set 3 (written last, not tuned on) : %.1f %%  (%d questions)  <- final figure" % (100 * acc3, n3))
    for intent in INTENTS:
        hits, total = per3.get(intent, (0, 0))
        if not total:
            continue
        print("  %-18s %d/%d" % (intent, hits, total))
    if mistakes3:
        print("\nmistakes on test set 3:")
        for sentence, wanted, guess, confidence in mistakes3:
            print("  %r\n      wanted %-16s got %-16s (%.2f)" % (sentence, wanted, guess, confidence))
    accuracy = acc3
    return accuracy


if __name__ == "__main__":
    main()
