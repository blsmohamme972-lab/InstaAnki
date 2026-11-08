'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const native = fs.readFileSync('android/src/com/instaanki/app/GithubFeedback.java','utf8');
const shell = fs.readFileSync('android/src/com/instaanki/app/MainActivity.java','utf8');
const web = fs.readFileSync('web/app.js','utf8');
const source = fs.readFileSync('web/learning.entry.js','utf8');

test('GitHub credentials never enter bundled HTML / JavaScript or Git history', () => {
  assert.doesNotMatch(web,/github_pat_[a-zA-Z0-9_]{30,}/);
  assert.match(native,/AndroidKeyStore/);
  assert.match(native,/AES\/GCM\/NoPadding/);
  assert.match(native,/GCMParameterSpec/);
  assert.match(shell,/TYPE_TEXT_VARIATION_PASSWORD/);
  assert.doesNotMatch(shell,/getGithubToken|return\s+.*token\s*;/);
});
test('only an explicitly paired owner can queue direct GitHub Issue reports', () => {
  assert.match(native,/boolean queue\(String raw\)/);
  assert.match(native,/!isPaired\(\)/);
  assert.match(native,/github_pat_/);
  assert.match(native,/api\.github\.com/);
  assert.match(native,/repos\/.*issues/);
  assert.match(native,/queued:/);
  assert.match(native,/prefs\.edit\(\)\.putString\(QUEUED\+id/);
  assert.match(native,/issueUrl|github\.com/);
});
test('Save choices keeps local report first and clearly distinguishes queued from delivered', () => {
  assert.match(web,/L\.reportFeedback\(lesson\.id/);
  assert.match(web,/native\.queueGithubReport\(JSON\.stringify\(stored\)\)/);
  assert.match(web,/Report queued for GitHub\. Waiting for Issue confirmation/);
  assert.match(web,/Report saved on this phone only\. Connect GitHub in Settings/);
  assert.match(web,/detail\.status === 'sent'/);
  assert.match(web,/GitHub Issue created successfully/);
  assert.match(source,/save\('feedback',id\)/);
});
test('reported IDs and source references are required; notes and learning history never shared', () => {
  assert.match(native,/source.*bookId/);
  assert.match(native,/questionNumber/);
  assert.match(native,/lessonVersion/);
  assert.match(native,/safeId\(lesson\)/);
  assert.doesNotMatch(native,/getAllNotes|reviewHistory/);
  assert.match(native,/validate\(new JSONObject\(raw\)\)/);
});
test('pairing and unpairing are available on the native Settings path', () => {
  assert.match(shell,/connectGithubReports\(\)/);
  assert.match(shell,/disconnectGithubReports\(\)/);
  assert.match(shell,/githubReportStatus\(\)/);
  assert.match(shell,/queueGithubReport\(String reportJson\)/);
  assert.match(web,/github-reporting/);
  assert.match(web,/github-disconnect/);
});

test('reports saved before pairing can be sent only with an explicit public-Issue confirmation', () => {
  assert.match(web,/function confirmSavedReportSubmission\(/);
  assert.match(web,/function submitSavedGithubReports\(/);
  assert.match(web,/github-send-saved/);
  assert.match(web,/github-confirm-send-saved/);
  assert.match(web,/public GitHub repository/);
  assert.match(web,/for \(const report of L\.getFeedback\(\)\)/);
  assert.match(web,/native\.queueGithubReport\(JSON\.stringify\(report\)\)/);
  assert.match(web,/No rejected report was erased/);
});
test('unpaired and rejected reports are explained separately and not claimed delivered', () => {
  assert.match(web,/Report saved on this phone only\. Connect GitHub in Settings/);
  assert.match(web,/GitHub queue rejected it/);
  assert.match(web,/Waiting for Issue confirmation/);
});

test('delivery errors expose safe HTTP classes and never leak tokens or GitHub error bodies', () => {
  assert.match(native,/GitHubHttpFailure/);
  assert.match(native,/status == 401/);
  assert.match(native,/status == 403/);
  assert.match(native,/status == 404/);
  assert.match(native,/SocketTimeoutException/);
  assert.match(native,/UnknownHostException/);
  assert.match(native,/LAST_ERROR/);
  assert.match(web,/Last delivery error:/);
  assert.match(web,/esc\(status\.lastError\)/);
  assert.doesNotMatch(native,/getErrorStream\(/);
});
test('stored token is distinct from an Issue-verified GitHub connection', () => {
  assert.match(native,/putBoolean\(VERIFIED,false\)/);
  assert.match(native,/putBoolean\(VERIFIED,true\)/);
  assert.match(web,/Token stored · not verified/);
  assert.match(web,/GitHub delivery verified by a successful Issue response/);
});
test('GitHub issue list deduplication uses repo-scoped Issues API not search API', () => {
  assert.match(native,/issues\?state=all&sort=created&direction=desc&per_page=100/);
  assert.doesNotMatch(native,/\/search\/issues/);
  assert.match(native,/new JSONArray\(response\)/);
});
