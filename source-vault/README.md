# Private source recovery

The extracted book source is delivered privately as `InstaAnki-Source-Archive.zip`. It is **not stored in GitHub**. Raw source extracts, encrypted `.iaenc` vault files and vault metadata are excluded from Git; this documentation and the optional export tool are public.

The private ZIP preserves structured questions and answers, extracted page text, the book cover, source figures, page renders, annotations and extraction audits. The original PDF is excluded. A manifest inside the archive records source-file hashes.

## Restore before producing another batch

Obtain the privately delivered `InstaAnki-Source-Archive.zip` from the user's saved files and place a local copy in the ignored `dist/` directory. From the repository root, extract to a temporary directory and copy the private source folder into its expected location:

```bash
python -m zipfile -e dist/InstaAnki-Source-Archive.zip dist/restored-source
mkdir -p private-content
cp -R dist/restored-source/private-content/. private-content/
python tools/production.py status
python tools/production.py next --count 10
```

Use a fresh `dist/restored-source` directory. Restore only `private-content/`; do not replace the current public production ledger with a historical source snapshot. Keep the ZIP, temporary restoration directory and recovered private files outside version control.

The authoritative production ledger is `production/books/shahzad-raja-2015-200-practice-questions.json`. Read it before selecting the next questions. Source-archive progress and draft files describe their snapshot time and do not override that ledger.

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
