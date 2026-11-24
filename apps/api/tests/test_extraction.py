"""The offline extractor must not know the wording of the held out layouts."""

from booklantern.extraction import offline

def test_old_heldout_wording_is_allowed_now_because_that_set_is_spent():
    """Version 1 of the reader had to stay free of the old held out layouts' wording. The independent test (docs/EXTRACTION-EVAL.md) showed that set was too small and
    written by the same author, so it was retired as a held out set and the reader was widened from general vocabulary (vocab.py). The independent sets A and B are
    never read for wording: tools/eval_independent.py only counts."""
    from booklantern.extraction import vocab

    assert vocab.label_field("Invoice No: A-1") == ("number", "A-1")
    assert offline.NAME.startswith("offline-rules-v2")


def test_scan_page_is_unreadable_not_guessed():
    from pathlib import Path
    data = (Path(__file__).resolve().parents[3] / "data" / "documents" / "D055.pdf").read_bytes()
    ex = offline.extract(data)
    assert ex.readable is False and ex.fields == {} and "OCR" in ex.notes[0]
