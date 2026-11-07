# Report a lesson problem and keep your progress

Open a lesson's feedback action and choose **Sound/audio**, **Images**, **Timing/sync**, **Question/answer**, **Wrong source**, or **Other**. Add an optional comment describing what happens and where in the lesson it happens. Save the report to keep it on this device.

Reports stay local until you explicitly choose **Share feedback** or **Save feedback file**. Sharing opens Android's chooser so you can select the destination. You can attach the resulting JSON file in this conversation when asking for a correction. Opening the chooser does not mean a report has been sent.

The feedback file contains your selected reasons and comments, stable lesson IDs, the version you reported, available source identifiers, available media checksums, and the app version. It excludes your private lesson notes, quiz answers, review history, and learning settings. No report is automatically posted to GitHub or another service.

**Hide lesson** controls whether the lesson appears in the feed and review queue. You can make it visible again later. **Dislike** records a separate preference. Neither action changes your quiz result, review schedule, or private note. A corrected lesson with the same ID keeps your existing progress; an older report continues to identify the version you originally reported.

## Install a correction or update

1. Use **Settings → Export learning backup** and keep the JSON file.
2. Use **Check for updates** for a published correction, or **Import lesson package** for a ZIP supplied directly to you.
3. Wait for the successful installation message. If a download is incomplete or its checksum differs from the catalog, the package is rejected and the installed content is retained.

The original 0.1.1 app requires a full close from Android's recent-apps screen and reopening after the Raja-only withdrawal ZIP. That correction removes the unrelated publication from active content while retaining the learning records separately.

If you see an incomplete-ZIP message, download the entire ZIP again and retry. Keep the previous installed app and its data. A lesson package updates content; app features require an APK signed with the same original Android signing identity. An APK signed with a different key cannot safely replace that installation. Until a compatible app update is available, the existing app can continue to use verified lesson-package imports.

The current three-lesson presentation update needs app **0.2.0 (version code 3)** for the new ending, clinical gallery and recap. Its ZIP cannot add that player code to 0.1.1. The repaired app reads a separate update catalog and blocks a package that requires a newer app before downloading; the old app's lesson catalog remains empty because it cannot enforce that requirement. The small Raja-only withdrawal ZIP remains the separate correction for removing the unrelated publication on 0.1.1.

Learning backups include the new feedback and visibility preferences. Older backups without those fields remain supported. Restoring a backup replaces the saved learning snapshot, so export the current snapshot first if you may need to return to it.
