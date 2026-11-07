# Private source recovery

The extracted book source is delivered privately as `InstaAnki-Source-Archive.zip`. It is **not stored in GitHub**. Raw source extracts, encrypted `.iaenc` vault files and vault metadata are excluded from Git; this documentation and the optional export tool are public.

The private ZIP preserves structured questions and answers, extracted page text, the book cover, source figures, page renders, annotations and extraction audits. The original PDF is excluded. A manifest inside the archive records source-file hashes.

## Find the source before requesting another upload

The active book is **Shahzad G. Raja, _200 Practice Questions in Cardiothoracic Surgery_ (2015)**, with book ID `shahzad-raja-2015-200-practice-questions`.

1. Check whether `private-content/book-metadata.json` and `private-content/questions.json` already contain that book and its 200 stable question IDs. A restored source does not require another ZIP upload.
2. If the private source is missing, look for an accessible source ZIP or the original PDF in the current task's attachments and private saved files. A statement that a file was delivered in an earlier chat does not prove it is accessible in this task.
3. Restore a matching ZIP, or rebuild from the matching PDF using the commands below. Ask for an upload only when neither is available.

Match the book identity before using source question numbers. The **MedCosmos 2008 collection with 156 questions is a different source**; its Q5 and Q54 cannot replace the Raja questions. Do not register a replacement book or reset existing progress to bypass a missing source.

## Restore a private ZIP

Place the matching archive in the ignored `dist/` directory. These commands use the existing `cryptography` dependency of `source_vault.py`; no encryption key is needed for an ordinary ZIP:

```bash
python tools/source_archive.py inspect dist/InstaAnki-Source-Archive.zip \
  --book shahzad-raja-2015-200-practice-questions
python tools/source_archive.py restore dist/InstaAnki-Source-Archive.zip \
  --book shahzad-raja-2015-200-practice-questions \
  --destination private-content
python tools/production.py --book shahzad-raja-2015-200-practice-questions status
python tools/production.py --book shahzad-raja-2015-200-practice-questions next --count 20
```

The recovery tool verifies file hashes, counts and book/question identities before writing. It accepts a new or empty destination, or an already identical restoration. It refuses to overwrite different private files and never writes a production ledger. Keep the ZIP and restored files outside version control.

## Rebuild from the original PDF

If the ZIP is unavailable, the supplied 190-page Raja PDF can recover the source. Install `PyMuPDF` in your Python environment if it is not already available. From the repository root:

```bash
python tools/extract_raja_source.py '/path/to/SHAHZAD _2015_ 200 Q _1_.pdf'
python tools/source_archive.py export --source private-content \
  --output dist/InstaAnki-Source-Archive.zip
```

The extractor reads the existing production ledger, verifies all 200 identities and recorded reviewed answer keys, and preserves the 32 question/answer figures, PDF annotations and page layout. It records duplicate answer passages, image-only choices/explanations, unlabeled options and floating formula annotations. These remain source-review concerns, not new medical or lesson-production approvals. The extractor does not change `needs_review` records. A separate documented source review may resolve a flag, as recorded for [Q37](../production/qa/q037-source-review.json).

Extraction requires a new output directory. Use `--output dist/rebuilt-source` when inspecting a new PDF alongside an existing source. Re-extracted JSON has a new checksum and must not be represented as the historical extraction. The original uploaded PDF is not copied into the repository, source ZIP, or app.

The authoritative production ledger remains `production/books/shahzad-raja-2015-200-practice-questions.json`. Read it before selecting the next questions. Archive progress fields describe a snapshot and never override that ledger. Recovering source does not recreate private narration drafts or mark new lessons produced.

## Preserve a usable backup

Deliver the verified `InstaAnki-Source-Archive.zip` to the user's private files with a download link and its SHA-256. Keep a durable private copy outside the execution workspace. Future tasks must actually have access to that file or to the restored source; the GitHub URL alone is insufficient. Do not claim a durable backup exists solely because a local ZIP was created.

Recovery tests:

```bash
python -m unittest discover -s tests -p 'test_source_recovery.py'
```

## Optional encrypted local export

`tools/source_vault.py` remains available for an additional encrypted private export. It requires Python's `cryptography` dependency:

```bash
python tools/source_vault.py encrypt
```

The tool builds a private ZIP, encrypts it with AES-256-GCM and verifies a decrypt/hash round trip. The encrypted `.iaenc` file, its metadata and the key are all private artifacts; do not add them to GitHub. Back up the key separately. Its contents are never printed by the tool.

To verify or recover an encrypted private export, supply the matching key using `--key` and choose private output paths:

```bash
python tools/source_vault.py verify --key private-recovery-key.json
python tools/source_vault.py decrypt --key private-recovery-key.json --output Recovered-Source.zip
```

The ordinary privately delivered ZIP does not require this encryption tool or key to restore. Neither restoration method needs the original PDF. Keep the Android signing identity separately so subsequent APKs can update the installed app.
