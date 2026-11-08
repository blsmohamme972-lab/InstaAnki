# GitHub-only reporting in InstaAnki Fresh 0.3.2

This feature works using **GitHub Issues** and the **GitHub API** directly from Android; no Vercel, third-party server, or GitHub token baked into APK.

## One-time owner setup (Android only)

1. In GitHub (https://github.com/settings/personal-access-tokens/new), create a **fine-grained personal access token**. Repository access: **Only select repositories** → `blsmohamme972-lab/InstaAnki`. Repository permission: **Issues: Read and write**, all other optional permissions: none. GitHub grants Metadata: read automatically.
2. Choose an expiration and keep the token private. Do not send it in ChatGPT, comments, screenshots or lessons.
3. In InstaAnki Fresh 0.3.2, open **Settings → Your data → GitHub issue reporting → Connect GitHub**. Paste it only into the **native Android password dialog**, not the web page.
4. The token is encrypted with an Android Keystore AES-GCM key and stays in app-private Android storage. The native Java layer calls `https://api.github.com`. Never expose the token through `AndroidNative.getItem`, web JavaScript, or a build artifact.
5. From a lesson, tap **Report → Images → Save choices**. The report is saved to the existing local feedback database first, queued in a private native queue, then submitted to GitHub Issues when connected.
6. A successful GitHub response creates an Issue containing the exact lesson ID, version, book/question binding, reason, optional comment and SHA-256 image/audio references; **private notes, grades and personal learning history are not included**. GitHub Issues in this repository are **public**; the UI warns before linking and reporting. Do not enter private information in reports.
7. When offline or rate-limited the report remains locally queued. Reopen the app or use **Retry pending reports**; its queue uses report IDs to prevent most duplicate issues. GitHub search is eventually consistent and not a concurrency-proof idempotency store. Avoid rapid retries after a successful request whose response was lost.
8. Disconnect from Settings whenever needed; pending reports remain on device and will not be sent until a new explicit connection.

## Replacement policy

Reports are triage signals, not authorization to alter medical explanations or generate art. A reviewed correction must keep the same lesson ID and book/question identity, increment the lesson version and use an appropriate compatible ZIP update. The existing importer rejects stale or mismatched sources and preserves notes, review history and progress. The current 0.3.2 feature **automates report submission, not image replacement**. Replacement still requires source/medical/visual QA and a separately published update.

## What GitHub Actions does

GitHub Actions compiles the actual Android native code and exercises Fresh browser + unit tests for the reporting feature. GitHub Issues store the received reports and provide notifications. A future reviewer can use labels/Projects and Actions workflows to triage them, but this project must not auto-publish unreviewed replacements.

## Current safeguards and limitations

- A non-owner of the repository should not be asked to supply a write token. This is a **personal owner-only workflow**.
- No anonymous reporting endpoint is exposed.
- A saved local report made before GitHub pairing is not automatically transmitted retroactively. This protects the user's earlier private feedback.
- No screenshot or video content is automatically uploaded, only approved metadata. The user can include a non-sensitive comment.
- An Android emulator/device test is separate from GitHub build validation; CI compilation is not proof of physical-device behavior.
