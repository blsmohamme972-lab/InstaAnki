"""Fail-closed source checks shared by production, narration and packaging.

The private extraction is the source of new work. Published content may only be
reused byte-for-byte against its recorded evidence; its existence is not a
substitute for the missing book. Hashes establish identity and integrity, not a
new medical review. There is deliberately no command-line override.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_BOOK = "shahzad-raja-2015-200-practice-questions"


class SourcePolicyError(ValueError):
    pass


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourcePolicyError(f"Cannot read source evidence {path}: {exc}") from exc


def text(value):
    return isinstance(value, str) and bool(value.strip())


def first(record, *keys):
    return next((record[k] for k in keys if k in record), None)


def content_fingerprints(lesson, *, authoring=False):
    """Compute review fingerprints without approving or writing any review.

    The same teaching content is expressed as mcq/headline/voice_text in private
    drafts and quiz/caption/transcript in public lessons. Media timing and asset
    checks happen separately. These hashes do not establish semantic accuracy;
    an actual comparison with the retained question and answer must precede the
    sourceReview record that approves them.
    """
    if not isinstance(lesson, dict) or not text(lesson.get("title")):
        raise SourcePolicyError("Reviewed teaching content requires a title")
    locus = lesson.get("locus")
    if not ((isinstance(locus, dict) and locus) or text(locus)):
        raise SourcePolicyError("Reviewed teaching content requires its memory locus")
    raw_scenes = lesson.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise SourcePolicyError("Reviewed teaching content requires its narrated scenes")
    scenes, ids = [], set()
    for scene in raw_scenes:
        if not isinstance(scene, dict):
            raise SourcePolicyError("Reviewed teaching scenes must be objects")
        normalized = {
            "id": scene.get("id"),
            "caption": scene.get("headline" if authoring else "caption"),
            "transcript": scene.get("voice_text" if authoring else "transcript"),
        }
        if not all(text(value) for value in normalized.values()) or normalized["id"] in ids:
            raise SourcePolicyError("Reviewed scenes need unique IDs, captions and exact narration")
        ids.add(normalized["id"])
        scenes.append(normalized)
    if authoring:
        mcq = lesson.get("mcq")
        if not isinstance(mcq, dict) or "quiz" in lesson:
            raise SourcePolicyError("Authoring review requires one unambiguous mcq object")
        options = mcq.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise SourcePolicyError("Reviewed MCQ requires keyed answer options")
        labels, values = [], []
        for option in options:
            if (not isinstance(option, dict) or not text(option.get("label"))
                    or not text(option.get("text")) or option["label"] in labels):
                raise SourcePolicyError("Reviewed MCQ options require unique labels and text")
            labels.append(option["label"])
            values.append(option["text"])
        answer = mcq.get("correct_answer_letter")
        if answer not in labels:
            raise SourcePolicyError("Reviewed MCQ requires an answer key matching its options")
        quiz = {"prompt": mcq.get("stem"), "options": values,
                "correctIndex": labels.index(answer), "explanation": mcq.get("explanation")}
    else:
        quiz = lesson.get("quiz")
        if not isinstance(quiz, dict) or "mcq" in lesson:
            raise SourcePolicyError("Assembled review requires one unambiguous quiz object")
        quiz = {key: quiz.get(key) for key in ("prompt", "options", "correctIndex", "explanation")}
    options, correct = quiz.get("options"), quiz.get("correctIndex")
    if (not text(quiz.get("prompt")) or not text(quiz.get("explanation"))
            or not isinstance(options, list) or len(options) < 2 or not all(text(o) for o in options)
            or isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct < len(options)):
        raise SourcePolicyError("Reviewed quiz requires a question, options, key and explanation")
    content = {"title": lesson["title"], "locus": locus, "scenes": scenes, "quiz": quiz}
    return {"authoredContentSha256": canonical_hash(content), "quizSha256": canonical_hash(quiz)}


def validate_content_review(question, lesson, evidence, *, authoring=False):
    """Require an explicit source comparison of this exact authored content."""
    review = question.get("sourceReview")
    if not isinstance(review, dict) or review.get("schemaVersion") != 1:
        raise SourcePolicyError(
            f"Q{question['number']} needs an actual source-content review before generation or completion. "
            "Copying sourceEvidence does not approve a script or quiz; record the reviewed content fingerprints.")
    if (not isinstance(evidence, dict) or review.get("sourceRecordSha256") != evidence.get("sourceRecordSha256")
            or review.get("evidenceSha256") != canonical_hash(evidence)):
        raise SourcePolicyError("Authored-content review is not bound to this exact source record and evidence")
    if (not text(review.get("reviewer")) or not text(review.get("notes"))
            or any(review.get(key) is not True for key in
                   ("sourceQuestionChecked", "keyedAnswerChecked", "explanationChecked"))):
        raise SourcePolicyError("Source-content review must name its reviewer, comparison notes and completed question/key/explanation checks")
    try:
        reviewed_at = datetime.fromisoformat(review.get("reviewedAt", "").replace("Z", "+00:00"))
        if reviewed_at.utcoffset() is None:
            raise ValueError("Timezone missing")
    except (ValueError, TypeError, AttributeError):
        raise SourcePolicyError("Source-content review requires an actual ISO reviewedAt timestamp with timezone")
    fingerprints = content_fingerprints(lesson, authoring=authoring)
    for key, actual in fingerprints.items():
        if review.get(key) != actual:
            raise SourcePolicyError(
                f"Q{question['number']} {key} differs from its source-reviewed content. "
                "Review the changed script and quiz against the source before regenerating or completing.")
    return fingerprints


def validate_publications(books, ledger):
    """Check publication identity and progress against the authoritative ledger."""
    if ledger.get("bookId") != ORIGINAL_BOOK:
        raise SourcePolicyError("Publication metadata requires the original-book ledger")
    if not isinstance(books, list) or len(books) != 1 or not isinstance(books[0], dict):
        raise SourcePolicyError("Publication metadata must contain exactly the original book")
    book = books[0]
    expected = {"id": ledger["bookId"], **{key: ledger.get(key) for key in ("title", "author", "year", "totalQuestions")}}
    for key, value in expected.items():
        if value is None or isinstance(book.get(key), bool) or book.get(key) != value:
            raise SourcePolicyError(f"Publication {key} differs from the original-book ledger")
    completed = sorted(q["number"] for q in ledger["questions"] if q["status"] == "produced")
    declared_numbers = book.get("completedQuestionNumbers")
    if (isinstance(book.get("completedVideos"), bool) or book.get("completedVideos") != len(completed)
            or not isinstance(declared_numbers, list)
            or any(isinstance(n, bool) or not isinstance(n, int) for n in declared_numbers)
            or declared_numbers != completed):
        raise SourcePolicyError("Publication completed counts or question numbers differ from actual produced ledger records")
    if "progress" in book and (isinstance(book["progress"], bool)
                               or book["progress"] != round(len(completed) / ledger["totalQuestions"] * 100, 1)):
        raise SourcePolicyError("Publication progress differs from actual produced ledger records")
    if "questions" in book:
        declared = book["questions"]
        if not isinstance(declared, list) or len(declared) != len(ledger["questions"]):
            raise SourcePolicyError("Publication question statuses differ from the original-book ledger")
        for shown, actual in zip(declared, ledger["questions"]):
            if (not isinstance(shown, dict) or isinstance(shown.get("number"), bool)
                    or shown.get("number") != actual["number"] or shown.get("lessonId") != actual.get("lessonId")):
                raise SourcePolicyError("Publication question identities differ from the original-book ledger")
            # A claim does not publish a lesson and need not rewrite app data.
            # Permit only ready/claimed display lag; produced and needs_review
            # claims must remain exact, as must every lesson ID and count.
            if (shown.get("status") != actual["status"]
                    and not (shown.get("status") in ("ready", "claimed") and actual["status"] in ("ready", "claimed"))):
                raise SourcePolicyError("Publication question statuses differ from the original-book ledger")


class SourcePolicy:
    def __init__(self, repo=ROOT):
        self.repo = Path(repo).resolve()
        self.policy = read_json(self.repo / "production/source-policy.json")
        if (self.policy.get("schemaVersion") != 1
                or self.policy.get("activeBookId") != ORIGINAL_BOOK):
            raise SourcePolicyError("The reviewed original-book source policy is missing or invalid")
        self.book_id = self.policy["activeBookId"]
        self._records = None

    def require_book(self, book_id):
        if book_id != self.book_id:
            raise SourcePolicyError(
                f"Source policy permits only {self.book_id}; received {book_id!r}. "
                "Do not substitute an authored collection or another book. "
                "A different source requires a separate explicit user decision and reviewed policy change.")
        return self.book_id

    def ledger(self):
        document = read_json(self.repo / "production/books" / f"{self.book_id}.json")
        self.check_ledger(document)
        return document

    def require_new_production(self):
        if self.policy.get("newProductionEnabled") is not True:
            raise SourcePolicyError(
                "New lesson production is paused by the current task scope. "
                "Only app repairs and reviewed updates to existing lessons are authorized. "
                "A new explicit user request and reviewed policy change are required to resume.")

    def check_ledger(self, document):
        self.require_book(document.get("bookId"))
        if document.get("source", {}).get("extractionSha256") != self.policy["source"]["questionsSha256"]:
            raise SourcePolicyError("The ledger extraction hash differs from the reviewed source policy")

    def _private_path(self, key):
        name = self.policy["source"][key]
        path = (self.repo / name).resolve()
        if not path.is_relative_to(self.repo / "private-content"):
            raise SourcePolicyError("Private source paths must remain inside private-content/")
        return path

    def source_records(self, document):
        self.check_ledger(document)
        questions_path = self._private_path("questionsFile")
        metadata_path = self._private_path("metadataFile")
        missing = [p.relative_to(self.repo).as_posix() for p in (questions_path, metadata_path) if not p.is_file()]
        if missing:
            raise SourcePolicyError(
                "Original Raja source is unavailable: " + ", ".join(missing) + ". "
                "Restore private-content/ from the verified InstaAnki-Source-Archive.zip, "
                "then rerun the source check. If only new scans are available, have the "
                "re-extraction reviewed and its new fingerprint explicitly approved in the "
                "source policy; do not rename another collection. New production is blocked.")
        expected = self.policy["source"]["questionsSha256"]
        raw_questions = questions_path.read_bytes()
        if hashlib.sha256(raw_questions).hexdigest() != expected:
            raise SourcePolicyError(
                "Private questions.json differs from the verified original extraction SHA-256. "
                "Restore the unmodified archive or review a new extraction and its policy fingerprint; "
                "changing bookId or a title cannot establish source evidence.")
        metadata = read_json(metadata_path)
        self.require_book(first(metadata, "id", "book_id", "bookId"))
        if self._records is not None:
            return self._records
        records = json.loads(raw_questions)
        if not isinstance(records, list) or len(records) != document.get("totalQuestions"):
            raise SourcePolicyError("Private question count differs from the original-book ledger")
        expected_ids = {q["number"]: q["id"] for q in document["questions"]}
        by_number = {}
        for record in records:
            n = record.get("source_question_number") if isinstance(record, dict) else None
            if (isinstance(n, bool) or not isinstance(n, int) or n in by_number
                    or record.get("id") != expected_ids.get(n)):
                raise SourcePolicyError("Private source records must match the ledger's unique stable question IDs")
            if "book_id" in record:
                self.require_book(record["book_id"])
            if "bookId" in record:
                self.require_book(record["bookId"])
            by_number[n] = record
        if set(by_number) != set(expected_ids):
            raise SourcePolicyError("Private source is missing original ledger questions")
        self._records = by_number
        return by_number

    def evidence_for(self, document, question):
        """Validate retained question AND keyed answer/explanation, then bind bytes."""
        record = self.source_records(document)[question["number"]]
        stem = first(record, "stem", "question_text", "question_stem", "question")
        options = record.get("options")
        answer = first(record, "correct_answer_letter", "answer_letter", "correct_answer")
        explanation = first(record, "explanation", "answer_explanation", "explanation_text")
        if not text(stem) or not isinstance(options, list) or len(options) < 2:
            raise SourcePolicyError(f"Q{question['number']} is missing a readable source question and options")
        labels = []
        for i, option in enumerate(options):
            label = option.get("label") if isinstance(option, dict) else chr(65 + i)
            value = option.get("text") if isinstance(option, dict) else option
            if not text(label) or not text(value) or label in labels:
                raise SourcePolicyError(f"Q{question['number']} has incomplete source answer options")
            labels.append(label)
        if not text(answer) or answer not in labels or not text(explanation):
            raise SourcePolicyError(f"Q{question['number']} is missing its keyed answer or readable source explanation")
        for key in ("source_question_pages", "source_answer_pages"):
            pages = record.get(key)
            if (not isinstance(pages, list) or not pages
                    or any(not isinstance(p, dict) or isinstance(p.get("printed_page"), bool)
                           or not isinstance(p.get("printed_page"), int) or p["printed_page"] < 1 for p in pages)):
                raise SourcePolicyError(f"Q{question['number']} is missing verifiable {key}")
        if question.get("status") == "needs_review":
            raise SourcePolicyError(f"Q{question['number']} still requires source review before production")
        record_hash = canonical_hash(record)
        review = question.get("sourceReview", {})
        if review.get("sourceRecordSha256", record_hash) != record_hash:
            raise SourcePolicyError(f"Q{question['number']} source record differs from its reviewed hash")
        if record.get("extraction_flags") or record.get("explanation_format") == "image_only":
            if (review.get("sourceRecordSha256") != record_hash
                    or review.get("remainingSourceFlags") != []):
                raise SourcePolicyError(f"Q{question['number']} extraction issues require a source-bound review")
        return {
            "schemaVersion": 1, "bookId": self.book_id,
            "questionNumber": question["number"], "questionId": question["id"],
            "extractionSha256": self.policy["source"]["questionsSha256"],
            "sourceRecordSha256": record_hash,
        }

    def check_claim_binding(self, question, evidence):
        if question.get("sourceEvidence") != evidence:
            raise SourcePolicyError(
                f"Q{question['number']} lacks the current source-evidence checkpoint. "
                "Claim the verified source question first; preserve its sourceEvidence in the authoring input.")

    def validate_authoring(self, document, lessons):
        if not isinstance(document, dict) or not lessons:
            raise SourcePolicyError("Authoring input must contain source-bound lessons")
        # A top-level declaration is optional only when every lesson carries an
        # explicit, checked sourceEvidence object. Audio filenames are not identity.
        declared = first(document, "bookId", "book_id")
        if declared is not None:
            self.require_book(declared)
        ledger = self.ledger()
        by_number = {q["number"]: q for q in ledger["questions"]}
        bindings = {}
        for lesson in lessons:
            supplied = lesson.get("sourceEvidence", {})
            if not isinstance(supplied, dict) or not supplied:
                raise SourcePolicyError(
                    "Authoring input is missing sourceEvidence. Restore the verified private source, "
                    "claim its question with production.py, and preserve that claim's sourceEvidence object.")
            self.require_book(supplied.get("bookId"))
            n = lesson.get("source_question_number", supplied.get("questionNumber"))
            if isinstance(n, bool) or not isinstance(n, int) or n not in by_number:
                raise SourcePolicyError("Authoring lesson has no stable original source question number")
            question = by_number[n]
            if question.get("status") != "produced":
                self.require_new_production()
            evidence = self.evidence_for(ledger, question)
            self.check_claim_binding(question, evidence)
            if supplied != evidence:
                raise SourcePolicyError(f"Q{n} authoring source evidence differs from the verified claim")
            if not text(lesson.get("id")) or lesson["id"] in bindings:
                raise SourcePolicyError("Authoring lessons need unique stable IDs")
            validate_content_review(question, lesson, evidence, authoring=True)
            bindings[lesson["id"]] = evidence
        return bindings

    def validate_lesson_source(self, lesson, document, question):
        self.check_ledger(document)
        if question.get("status") != "produced":
            self.require_new_production()
        source = lesson.get("source", {})
        self.require_book(source.get("bookId"))
        if source.get("questionNumber") != question["number"]:
            raise SourcePolicyError("Lesson and ledger question identities differ")
        evidence = self.evidence_for(document, question)
        self.check_claim_binding(question, evidence)
        if (source.get("questionId") != evidence["questionId"]
                or source.get("evidenceSha256") != canonical_hash(evidence)):
            raise SourcePolicyError("Lesson must carry the claimed questionId and exact source evidenceSha256")
        validate_content_review(question, lesson, evidence)
        return evidence

    def published_validation(self, lesson, document, question):
        """Return frozen validation only for the three already published sources."""
        self.check_ledger(document)
        self.require_book(lesson.get("source", {}).get("bookId"))
        anchor = self.policy.get("publishedSourceRecords", {}).get(str(question["number"]))
        if not anchor or question.get("status") != "produced":
            return None
        if (question.get("lessonId") != anchor["lessonId"]
                or lesson.get("id") != anchor["lessonId"]
                or lesson.get("source", {}).get("questionNumber") != question["number"]
                or question.get("sourceReview", {}).get("sourceRecordSha256") != anchor["sourceRecordSha256"]
                or question.get("expectedQuizSha256") != anchor["quizSha256"]
                or canonical_hash(lesson.get("quiz")) != anchor["quizSha256"]
                or question.get("qaReport", {}).get("sourceChecked") is not True):
            raise SourcePolicyError("Published lesson no longer matches its ledger-bound original source review")
        old = question.get("productionValidation", {})
        candidates = []
        if canonical_hash(old) == anchor["validationSha256"]:
            candidates.append(old)
        for report in self.policy.get("publishedRevisionReports", []):
            path = self.repo / report["path"]
            if not path.is_file() or file_hash(path) != report["sha256"]:
                raise SourcePolicyError("Published revision evidence changed or is missing; review it before repackaging")
            candidates.extend(read_json(path).get("assetInspection", {}).get("lessons", []))
        for validation in candidates:
            if (validation.get("sourceQuestionId") == question["id"]
                    and validation.get("quizSha256") == anchor["quizSha256"]
                    and validation.get("lessonSha256") == canonical_hash(lesson)):
                return validation
        raise SourcePolicyError("Published lesson bytes changed; exact released content is required until source review is restored")

    def verify_frozen_assets(self, lesson, validation, web_root):
        web_root = Path(web_root).resolve()
        if validation.get("lessonSha256") != canonical_hash(lesson):
            raise SourcePolicyError("Lesson differs from its completed production hash")
        media = validation.get("mediaSha256")
        if not isinstance(media, dict) or not media:
            raise SourcePolicyError("Completed lesson has no recorded media hashes")
        for name, expected in media.items():
            relative = PurePosixPath(name)
            path = (web_root / name).resolve()
            if (not name.startswith("media/") or ".." in relative.parts
                    or not path.is_relative_to(web_root) or not path.is_file()
                    or file_hash(path) != expected):
                raise SourcePolicyError(f"Published media changed or is missing: {name}")
        audio = lesson.get("audioUrl", "").lstrip("/")
        if audio not in media:
            raise SourcePolicyError("Published audio is not bound to the production record")
        timing = (web_root / audio).with_suffix(".timing.json")
        if not timing.is_file() or file_hash(timing) != validation.get("audioTimingSha256"):
            raise SourcePolicyError("Published audio timing changed or is missing")

    def validate_pack(self, lessons, web_root):
        if not isinstance(lessons, list) or not lessons:
            raise SourcePolicyError("A normal content pack must contain source-bound lessons")
        # Inspect every identity before accepting even one lesson from a mixed pack.
        for lesson in lessons:
            self.require_book(lesson.get("source", {}).get("bookId"))
        document = self.ledger()
        by_number = {q["number"]: q for q in document["questions"]}
        for lesson in lessons:
            n = lesson["source"].get("questionNumber")
            question = by_number.get(n) if isinstance(n, int) and not isinstance(n, bool) else None
            if question is None or question.get("status") != "produced":
                raise SourcePolicyError(f"Question {n!r} is not a completed original-book lesson")
            validation = self.published_validation(lesson, document, question)
            if validation is None:
                evidence = self.validate_lesson_source(lesson, document, question)
                validation = question.get("productionValidation", {})
                if validation.get("sourceEvidenceSha256") != canonical_hash(evidence):
                    raise SourcePolicyError("Completed production is not bound to this source evidence")
                if validation.get("sourceReviewSha256") != canonical_hash(question.get("sourceReview")):
                    raise SourcePolicyError("Completed production is not bound to the current authored-content review")
                if question.get("qaReport", {}).get("sourceChecked") is not True:
                    raise SourcePolicyError("Packaging requires the completed source review")
            self.verify_frozen_assets(lesson, validation, web_root)


def require_book(book_id):
    return SourcePolicy().require_book(book_id)


def validate_authoring(document, lessons):
    return SourcePolicy().validate_authoring(document, lessons)


def validate_pack(lessons, web_root):
    return SourcePolicy().validate_pack(lessons, web_root)
