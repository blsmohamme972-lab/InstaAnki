# One-tap reports — integration prototype

This branch contains an **undeployed receiver prototype**, not an enabled phone feature.

## What works

- A user-authorized report can be validated by a Node/Vercel HTTPS function at `POST /api/feedback`.
- Authentication uses a **private receiver pairing secret** set as `INSTAANKI_REPORT_TOKEN`, never stored in a public repository or bundled app.
- Server-only GitHub token `GITHUB_ISSUES_TOKEN` can create issues with Issues:write permission scoped only to `blsmohamme972-lab/InstaAnki`.
- The receiver sends only a report ID, lesson ID/revision, reason, optional comment, source book/question, timestamp and up to 10 asset SHA-256 references. No private study notes or review history.
- The receiver checks GitHub for an existing issue containing the same ID before creation. This is a best-effort repeat guard, not atomic deduplication under concurrent retries.
- Unit tests use mocked GitHub requests and cannot accidentally create live issues.

## Deploy securely (owner action required)

1. Connect and deploy via a secure HTTPS host (for example, Vercel).
2. Configure private environment variables `GITHUB_ISSUES_TOKEN` and a random, 32+ character `INSTAANKI_REPORT_TOKEN`; never place them in source, an APK, or public website JavaScript.
3. Enable only explicitly paired devices; preferably use device-scoped credentials backed by Android Keystore and server-side storage with revocation and rate limits before production.
4. Publish a fixed, verified endpoint to a future app release. The Android native bridge must submit reports with the user's opt-in, queue offline reports, and acknowledge the GitHub issue only after a successful HTTP response. It must never include the server's GitHub token.
5. Require review of any medical facts, image provenance, source binding and higher lesson version before publishing a replacement. The existing importer validates identity and preserves learning history; do not silently rewrite lessons.

## Privacy and safety

The repository is public: issue titles, reasons, and comments may be visible to everyone. Before enabling automatic submission, show clear privacy consent and keep notes and learning data local. A `Save choices` action in existing released APKs **does not transmit** reports. This prototype does not change that. This route cannot create images, replace a lesson, distribute a pack, or awaken a ChatGPT conversation by itself.

Manual GitHub transport smoke test: [issue #7](https://github.com/blsmohamme972-lab/InstaAnki/issues/7), explicitly marked as a synthetic test.
