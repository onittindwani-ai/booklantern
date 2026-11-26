# Extraction evaluation

What this measures: how many fields the built in reader gets right when it reads a bill PDF. The built in reader is `offline-rules-v1`. **It is rules, not a language model.** It reads the text layer of a PDF and cannot read a scan.

## Read this first

- **The same person wrote both sets.** One author wrote the dev set, the held out set and the reader. Different layouts and wording are not the same as documents from real vendors. These are not independent scores and do not predict real world accuracy.
- **The live path is UNVERIFIED.** The reader that uses a language model is written but was never run, so no number here says anything about it. It cannot yet send page images through the base wrapper.
- The seed documents are sample documents and labelled as sample data.

## Dev set

<!--n:seed.dev_documents-->60<!--/n--> documents in layouts A to D, including <!--n:seed.dev_scans-->6<!--/n--> scans with no text layer. The reader was built and tuned against the 54 readable ones, so its **100 percent** on them is a tuned number and proves little. The 6 scans are reported as not readable, not as wrong.

## Held out set

<!--n:heldout_documents-->24<!--/n--> documents in layouts E to H with different labels and wording. The generator was written **before** the reader. The reader was run on them **once**, and the result was saved untouched in `data/eval/heldout_first_run.json` (commit "test: first held out extraction run, saved untouched"). The reader was not tuned afterwards at the time. It is **no longer held out**: the independent test below showed this set was too small and written by the same author as the reader, so the reader was later widened with general vocabulary and this set now counts as a development check (the old wording guard test was retired for that reason).

Result of that first run: overall field accuracy **37.8 percent**, and **0 of 24 documents** had every field right.

| Field | Correct | Accuracy |
| --- | --- | --- |
| vendor | 18 of 24 | 75.0 percent |
| number | 0 of 24 | 0.0 percent |
| issue_date | 0 of 24 | 0.0 percent |
| due_date | 0 of 24 | 0.0 percent |
| currency | 6 of 24 | 25.0 percent |
| po | 16 of 24 | 66.7 percent |
| bill_to | 0 of 24 | 0.0 percent |
| subtotal_minor | 0 of 24 | 0.0 percent |
| tax_minor | 12 of 24 | 50.0 percent |
| total_minor | 6 of 24 | 25.0 percent |
| bank_account | 24 of 24 | 100.0 percent |
| tax_rate_bp | 12 of 24 | 50.0 percent |
| line_totals | 24 of 24 | 100.0 percent |

The dates, the bill number and the Bill to name were not found at all, because the held out layouts word their labels differently. That is exactly what a held out set is for. The review screen shows low confidence for such fields, and the checks by code still catch a wrong total on whatever was read.


## Independent test: set A and set B (written by separate AI test authors who never saw the code)

Two sets of sample bills were written by two separate AI test authors who read only the system's description files (SPEC, START-HERE, CAPABILITIES), never the code, the seed or the tests: **set A has 53 documents (17 vendors, 8 layout families, 6 languages)** and **set B has 52 documents (19 vendors, 14 other layout families, 9 languages, more date and number styles)**. Each holds 4 documents that a person must key (empty text layer, noise, a continuation page only, a cash note, a page with two invoices) and 4 credit notes. The files, their keys and the test authors' README are in `data/eval/independent/set_a` and `set_b`. The text files are the text layer of a bill; the scorer turns them into rows of cells, 5.5 points per character, the same split the PDF reader uses (`tools/eval_independent.py`, its docstring fixes every scoring choice before any run). The PDF drawing is not tested, only the reading of text.

How it was run, in this order, and what each step means:

1. The scorer and its unit tests (on small handmade bills) were written without running them on engine changes. Set A was copied in. The README of the sets was read first; while building the scorer I also printed the shape of `context.json` and so saw set A's vendor names (no vendor name was used in the reader). Nothing in the A or B documents was read.
2. **Set A first run with the first reader (`offline-rules-v1`)**: saved untouched in `data/eval/independent/set_a_first_run.json` and committed.
3. The reader was rewritten as `offline-rules-v2` from general document knowledge only: every page, labels in nine languages, decimal comma and other number styles, 15 date styles with a day or month swap guess flagged at low confidence, tax lines added up and checked, tax included bills, credit note wording, an IBAN shape. The seed documents were the only test data used while writing it, plus handmade bills in `apps/api/tests/test_extraction_v2.py`.
4. **Set B first run with the v2 reader**: saved untouched in `set_b_first_run.json` and committed. Set B was copied only after step 3 was committed.
5. Set A was run again (`set_a_after_tuning.json`). **Set A is no longer held out** after this, because the reader was changed after seeing its score. Set B stayed held out for the reader as it was at that run, with this caveat: the test authors' README, which was read, lists set B's languages, layout families and date styles, so B was blind in its items but not in its format families.
6. A small second pass (`v2.1`): the bank account is read only by an IBAN shape (other country formats are not guessed), and the scorer counted every unusable page as "no text layer" (a scorer bug, fixed: only a page with no text at all is). This pass looked at counts of false flags per code, not at documents. Both sets were rerun and saved as `set_a_after_v2_1.json` and `set_b_after_v2_1.json`; the first runs were rescored with the fixed scorer in throwaway copies of the code at those commits (`*_first_run_rescored.json`). Both sets are spent for any further change.

| | Old self written held out set (24) | Set A first run, reader v1 | Set A, reader v2 (not held out) | **Set B first run, reader v2** |
| --- | --- | --- | --- | --- |
| Field accuracy (all fields scored) | 37.8 percent | 40.6 percent | 81.4 percent | **75.2 percent** |
| Documents with every field right | 0 of 24 | 0 of 49 | 7 of 49 | **5 of 48** |
| Hard documents handled (unreadable or low confidence on every field) | not measured | 1 of 4 | 4 of 4 | **3 of 4** |
| Fields at confidence 80 or more and wrong | not measured | 13 | 6 | **5** |
| Findings found, scorer as first written | not measured | 7 of 16 | 12 of 16 | 11 of 16 |
| Findings found, scorer fixed (v2.1 code) | | 7 of 16 | 15 of 16 | **13 of 16** |
| False flags (findings raised that the key does not expect), fixed scorer | not measured | 92 | 64 | **75** |

Field accuracy per field, set B first run: vendor 83.3, invoice number 79.2, invoice date 91.7, due date 47.9, currency 75.0, subtotal 81.2, tax 81.2, total 87.5, line amounts 50.0 percent. Set A with reader v2: vendor 100, number 61.2, date 100, due date 77.6, currency 77.6, subtotal 95.9, tax 73.5, total 89.8, line amounts 57.1 percent. "Every field right" is harsh on purpose: one wrong line amount fails the document.

**Plain reading.**

- The honest number for a bill the reader has never seen is the set B first run: about **3 fields in 4 right**, and **1 document in 10 with nothing wrong**. That is a stand in that finds the header, the dates and the totals most of the time, not a replacement for a person looking at each bill. The review screen exists for exactly this.
- The confidence numbers are useful but cautious: on set B a field at 80 or more was right 97 percent of the time (173 of 178), one between 50 and 79 was right 92 percent (114 of 124), and the 8 fields under 50 (all guessed day or month dates) were all right, so the low band sends a person to look at fields that were fine. Only 5 fields were confidently wrong.
- The checks by code do their job: a printed wrong total, a changed bank detail, a duplicate, a date in the future, a bill to another company, a missing purchase order are found (13 of 16 expected findings on set B, 15 of 16 on A with the fixed scorer).
- **The cost is false alarms: about 75 on 52 documents.** Most are line sum mismatches (22 on B) and total mismatches (11): the reader sometimes picks a wrong number from a busy layout, and then the arithmetic check correctly says the numbers do not add up. A person looks and fixes it. That is the safe direction (an alarm, not a silent wrong number) but it is noisy.
- Where it is weak: due dates (it reads only a printed one; terms such as "month end plus 30" are not worked out by the reader, the intake adds net 30 instead), line items (a table with no quantity column, hours times a rate, carried forward lines), a label block followed by a value block, side by side seller and buyer, a bill that prints a second currency, and numeric dates where day and month could be swapped (the reader reports such a date at 40 percent confidence on purpose, so it lands on the review list). Japanese, Polish and Portuguese bills are read worse than English ones.
- Not extracted by this system at all: payment terms (the rest of the system uses net 30 or the vendor's terms). Bill or credit note is read right on 48 of 49 documents of set A and 43 of 44 of set B (extracted as `doc_type`), and a credit note raises a warning; they are not turned into negative bills.
- Scanned pages and pictures are never read here (no OCR). A live model with image input would be needed; the base wrapper takes text only.

**What was not tested:** the PDF drawing path (the sets are text), real vendor PDFs, a live model (see docs/14 and the model path below), set B items one by one (not read), and any country's tax rules (no tax advice is given: the reader only compares the printed rate with the vendor's usual rates).

## Other evals

- **Planted problems and bank matching:** `python tools/score_seed.py` checks 25 planted document problems (duplicates counted per pair; found 25 of 25, 0 extra flags) and the bank answer key (184 of 184 lines as the key says). The same author wrote the seed and the checks.
- **Duplicates:** exact and near duplicate detection, scored per pair, in `score_seed.py`.
- **Property tests:** the forecast (deterministic, cash adds up, never more than is owed), the reminder stop rules on 400 random worlds of 90 days each, and money rounding. See `apps/api/tests/`.
