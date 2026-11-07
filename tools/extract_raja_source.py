#!/usr/bin/env python3
"""Rebuild the private source from the 190-page Shahzad Raja 2015 PDF.

Requires PyMuPDF. Source answers, duplicate passages and layout dependencies
are preserved, not medically corrected. The production ledger is read only.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

BOOK = "shahzad-raja-2015-200-practice-questions"
ROOT = Path(__file__).resolve().parents[1]
QUESTION = re.compile(r"^[ \t]*(\d{1,3})\.\s+", re.M)
ANSWER = re.compile(r"^[ \t]*(\d{1,3})\.\s*Answer:\s*([A-E])", re.M)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(text):
    return re.sub(r"\s+", " ", text).strip()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sections(pages, pattern):
    text, ranges = "", []
    for page in pages:
        start = len(text)
        text += page["body_text"] + "\n"
        ranges.append((start, len(text), page["pdf_page"]))
    matches = list(pattern.finditer(text))
    records = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content_end = match.start() + len(text[match.start():end].rstrip())
        records.append({"number": int(match[1]), "text": text[match.end():end].strip(),
                        "answer": match[2] if pattern is ANSWER else None,
                        "pages": [{"pdf_page": n, "printed_page": n - 12}
                                  for start, stop, n in ranges if start < content_end and stop > match.start()]})
    return records


def parse_options(number, text):
    matches = list(re.finditer(r"^\s*([A-E])\.\s*", text, re.M))
    if number == 103 and not matches:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 6 or not lines[-6].endswith("incidence of WPW is"):
            raise ValueError("Q103: unrecognized unlabeled-choice layout")
        return compact(" ".join(lines[:-5])), [
            {"label": label, "text": value, "label_inferred_from_order": True}
            for label, value in zip("ABCDE", lines[-5:])], list("ABCDE")
    labels = [match[1] for match in matches]
    if sorted(labels) != list("ABCDE"):
        raise ValueError(f"Q{number}: expected five distinct labeled choices, found {labels}")
    options = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = compact(text[match.end():end])
        if not value and number != 23:
            raise ValueError(f"Q{number}: unexpected empty choice {match[1]}")
        options.append({"label": match[1], "text": value or None,
                        "format": "text" if value else "image"})
    return compact(text[:matches[0].start()]), sorted(options, key=lambda option: option["label"]), labels


def heading_positions(document, first, last, pattern):
    result = []
    for page_number in range(first, last + 1):
        for block in document[page_number - 1].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"])
                match = pattern.match(text)
                if match:
                    result.append((page_number * 1000 + line["bbox"][1], int(match[1])))
    return sorted(result)


def extract(pdf, output, ledger_path):
    import fitz

    pdf, output, ledger_path = Path(pdf), Path(output), Path(ledger_path)
    if output.exists():
        raise ValueError("Choose a new extraction directory; existing source is not replaced")
    ledger_bytes = ledger_path.read_bytes()
    ledger = json.loads(ledger_bytes)
    if ledger.get("bookId") != BOOK or ledger.get("totalQuestions") != 200:
        raise ValueError("The ledger does not describe the Shahzad Raja 200-question book")
    ledger_questions = {question["number"]: question for question in ledger["questions"]}
    if set(ledger_questions) != set(range(1, 201)) or any(
            q["id"] != f"{BOOK}-q{n:03d}" for n, q in ledger_questions.items()):
        raise ValueError("Ledger source identities are incomplete or incompatible")
    with fitz.open(pdf) as document:
        if (len(document) != 190 or "SHAHZAD G. RAJA" not in document[4].get_text()
                or "200 PRACTICE QUESTIONS" not in document[4].get_text()):
            raise ValueError("Expected the 190-page Shahzad Raja 2015 source PDF")
        pages = [{"pdf_page": i + 1, "printed_page": i - 11 if i >= 12 else None,
                  "text": page.get_text(), "body_text": page.get_text(clip=fitz.Rect(0, 60, page.rect.width, page.rect.height))}
                 for i, page in enumerate(document)]
        question_headings = heading_positions(document, 13, 79, QUESTION)
        answer_headings = heading_positions(document, 81, 185, ANSWER)
        parsing_pages = [dict(page) for page in pages]
        supplemental = []
        # Floating formula boxes occur late in PDF object order. Keep them as
        # separate annotations on the question at their visible position, rather
        # than accidentally attaching them to a later question's last option.
        for page_number in range(13, 186):
            previous_y = 0
            headings = question_headings if page_number < 81 else answer_headings
            for block in document[page_number - 1].get_text("blocks"):
                if block[1] < 60 or not block[4].strip() or block[6] != 0:
                    continue
                if block[1] < previous_y - 10:
                    body = parsing_pages[page_number - 1]["body_text"]
                    if body.count(block[4]) != 1:
                        raise ValueError("Could not isolate a floating source annotation")
                    parsing_pages[page_number - 1]["body_text"] = body.replace(block[4], "", 1)
                    owner = [(p, n) for p, n in headings if p <= page_number * 1000 + block[1]][-1][1]
                    supplemental.append({"question_number": owner, "pdf_page": page_number,
                                         "section": "question" if page_number < 81 else "answer",
                                         "bbox": list(block[:4]), "text": block[4].strip()})
                previous_y = max(previous_y, block[1])
        question_sections = sections(parsing_pages[12:79], QUESTION)
        answer_sections = sections(parsing_pages[80:185], ANSWER)
        if [q["number"] for q in question_sections] != list(range(1, 201)):
            raise ValueError("The PDF question sequence is not exactly 1–200")
        by_answer = defaultdict(list)
        for answer in answer_sections:
            by_answer[answer["number"]].append(answer)
        if set(by_answer) != set(range(1, 201)):
            raise ValueError("The PDF does not contain an answer for every question")
        questions = []
        for section in question_sections:
            number = section["number"]
            answers = by_answer[number]
            if len({answer["answer"] for answer in answers}) != 1:
                raise ValueError(f"Q{number}: conflicting source answer keys")
            stem, options, order = parse_options(number, section["text"])
            if not stem:
                raise ValueError(f"Q{number}: empty question")
            flags = list(dict.fromkeys(ledger_questions[number].get("sourceReviewFlags", [])))
            if order != list("ABCDE"):
                flags.append("source_option_order_nonsequential")
            if len(answers) > 1:
                flags.append("duplicated_answer_in_source")
            explanation = max((answer["text"] for answer in answers), key=len)
            if not explanation:
                flags.append("image_only_explanation")
            answer_pages = sorted({p["pdf_page"] for answer in answers for p in answer["pages"]})
            cross_refs = sorted({int(n) for n in re.findall(r"(?:answer|question)\s+(?:to\s+)?(\d+)", explanation, re.I)})
            if any(n not in by_answer for n in cross_refs):
                raise ValueError(f"Q{number}: unresolved source cross-reference")
            questions.append({
                "id": f"{BOOK}-q{number:03d}", "book_id": BOOK, "source_question_number": number,
                "stem": stem, "options": options, "source_option_order": order,
                "correct_answer_letter": answers[0]["answer"], "explanation": explanation or None,
                "explanation_format": "text" if explanation else "image_only",
                "source_question_pages": section["pages"],
                "source_answer_pages": [{"pdf_page": n, "printed_page": n - 12} for n in answer_pages],
                "source_answer_occurrences": answers, "source_answer_cross_references": cross_refs,
                "source_supplemental_text": [item for item in supplemental if item["question_number"] == number],
                "recorded_source_review": ledger_questions[number].get("sourceReview"),
                "source_figure_ids": [], "extraction_flags": sorted(set(flags)),
                "raw_question_text": section["text"], "clinical_correctness_verified": False,
            })
        for number, record in ledger_questions.items():
            original_key = record.get("sourceReview", {}).get("sourceAnswerLetter")
            if original_key is not None and questions[number - 1]["correct_answer_letter"] != original_key:
                raise ValueError(f"Q{number}: source key conflicts with the existing produced lesson")

        pdf_annotations = []
        for index, page in enumerate(document):
            for annotation in page.annots() or []:
                pdf_annotations.append({"pdf_page": index + 1, "type": annotation.type[1],
                                        "bbox": list(annotation.rect), "info": annotation.info,
                                        "authority": "User/source PDF annotation; does not override the printed answer key."})

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".raja-extract-", dir=output.parent))
        try:
            (temporary / "source-figures").mkdir()
            figures = []
            for page_number in range(13, 186):
                page = document[page_number - 1]
                phase = "question" if page_number < 81 else "answer"
                headings = question_headings if phase == "question" else answer_headings
                masks = {image[0]: image[1] for image in page.get_images(full=True)}
                for image in sorted(page.get_image_info(xrefs=True), key=lambda item: (item["bbox"][1], item["bbox"][0])):
                    position = page_number * 1000 + image["bbox"][1]
                    preceding = [(p, n) for p, n in headings if p <= position]
                    if not preceding:
                        raise ValueError("Could not associate a source figure with a question/answer")
                    number = preceding[-1][1]
                    identity = f"figure-{len(figures) + 1:03d}"
                    relative = f"source-figures/{identity}.png"
                    pixmap = fitz.Pixmap(document, image["xref"])
                    if masks.get(image["xref"]) and not pixmap.alpha:
                        pixmap = fitz.Pixmap(pixmap, fitz.Pixmap(document, masks[image["xref"]]))
                    if pixmap.colorspace and pixmap.colorspace.n > 3:
                        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                    pixmap.save(temporary / relative)
                    # Decode the saved bytes to check extraction, not medical content.
                    decoded = fitz.Pixmap(str(temporary / relative))
                    if (decoded.width, decoded.height) != (image["width"], image["height"]):
                        raise ValueError("Extracted figure dimensions changed")
                    figures.append({"id": identity, "path": relative, "pdf_page": page_number,
                                    "printed_page": page_number - 12, "section": phase,
                                    "question_number": number, "bbox": list(image["bbox"]),
                                    "pdf_xref": image["xref"], "width": decoded.width, "height": decoded.height,
                                    "sha256": digest((temporary / relative).read_bytes()),
                                    "full_embedded_raster_preserved": True})
                    questions[number - 1]["source_figure_ids"].append(identity)
            if len(figures) != 32:
                raise ValueError(f"Expected 32 question/answer figures; found {len(figures)}")
            q23_figures = [f for f in figures if f["question_number"] == 23 and f["section"] == "question"]
            if len(q23_figures) != 5:
                raise ValueError("Q23: could not recover all five image answer choices")
            for option, figure in zip(questions[22]["options"], q23_figures):
                option["source_figure_id"] = figure["id"]
            for question in questions:
                if question["explanation_format"] == "image_only" and not any(
                        f["question_number"] == question["source_question_number"] and f["section"] == "answer" for f in figures):
                    raise ValueError("Image-only explanation has no preserved figure")
            (temporary / "page-renders").mkdir()
            # Retain page layout for every question/answer, including equations and tables.
            for n in [1, *range(13, 186)]:
                document[n - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(temporary / "page-renders" / f"page-{n:03d}.png")
            document[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(temporary / "book-cover.jpeg")
            for question in questions:
                page_numbers = sorted({p["pdf_page"] for p in question["source_question_pages"] + question["source_answer_pages"]})
                question["layout_page_renders"] = [f"page-renders/page-{n:03d}.png" for n in page_numbers]
            timestamp = datetime.now(timezone.utc).isoformat()
            metadata = {"schema_version": 1, "id": BOOK, "title": "200 Practice Questions in Cardiothoracic Surgery",
                        "author": "Shahzad G. Raja", "year": 2015, "question_count": 200,
                        "source_pdf_filename": pdf.name, "source_pdf_sha256": digest(pdf.read_bytes()),
                        "pdf_page_count": 190, "printed_page_offset": 12,
                        "original_pdf_included": False, "extracted_at": timestamp,
                        "recovery_note": "Re-extracted from the uploaded PDF. This recovery is not byte-identical to the historical extraction; current production progress remains in the repository ledger."}
            write_json(temporary / "questions.json", questions)
            report = {"schema_version": 1, "book_id": BOOK, "extracted_at": timestamp,
                      "question_count": 200, "unique_source_ids": True, "all_questions_have_five_options": True,
                      "all_questions_have_valid_single_answer_keys": True, "figure_count": len(figures),
                      "all_figures_decode": True, "page_render_count": 174,
                      "pdf_annotation_count": len(pdf_annotations),
                      "duplicate_answer_question_numbers": [n for n, rows in by_answer.items() if len(rows) > 1],
                      "image_only_options": [23], "inferred_option_labels": [103],
                      "floating_annotation_question_numbers": sorted({item["question_number"] for item in supplemental}),
                      "image_only_explanations": [q["source_question_number"] for q in questions if q["explanation_format"] == "image_only"],
                      "source_cross_references": {str(q["source_question_number"]): q["source_answer_cross_references"] for q in questions if q["source_answer_cross_references"]},
                      "existing_completed_keys_verified": {str(n): questions[n-1]["correct_answer_letter"] for n in [5, 54, 182]},
                      "existing_completed_question_numbers": ledger["completedQuestionNumbers"],
                      "existing_review_blockers_preserved": sum(q["status"] == "needs_review" for q in ledger["questions"]),
                      "production_ledger_sha256": digest(ledger_bytes), "production_ledger_modified": False,
                      "questions_sha256": digest((temporary / "questions.json").read_bytes()),
                      "clinical_correctness_verified": False,
                      "scope": "Source recovery and structural verification; no new lessons or clinical sign-off."}
            write_json(temporary / "book-metadata.json", metadata)
            write_json(temporary / "book-pages.json", pages)
            write_json(temporary / "source-figures.json", {"book_id": BOOK, "figures": figures})
            write_json(temporary / "source-annotations.json", {"book_id": BOOK, "annotations": supplemental,
                "pdf_annotations": pdf_annotations,
                "scope": "Source layout and PDF annotations; use the current taxonomy when authoring new lessons."})
            write_json(temporary / "extraction-report.json", report)
            write_json(temporary / "figure-qa.json", {
                "book_id": BOOK, "scope": "All 32 embedded rasters recovered and decoded; layout retained separately. Medical and lesson visual review remain separate.",
                "final_asset_fidelity_summary": {"repair_required": 0, "extracted_rasters": len(figures)},
                "all_figures_decode": True, "clinical_correctness_verified": False})
            (temporary / "RECOVERY.txt").write_text(
                "InstaAnki private source recovery\n\nBook: Shahzad G. Raja, 200 Practice Questions in Cardiothoracic Surgery (2015).\n"
                "This archive contains all 200 source questions, source keys and explanations, 32 source figures, page text and 174 layout renders.\n"
                "Restore private-content/ into the repository's private-content/ directory. Never overwrite production/books/.\n"
                f"The repository ledger is authoritative: at recovery, Q5, Q54 and Q182 were produced; {report['existing_review_blockers_preserved']} review blockers remained.\n"
                "This is a new extraction, not the historical extraction identified by older hash values.\n"
                "Keep this ZIP in your private saved files and attach it to future production chats when the source is missing.\n"
                "Do not publish the source ZIP, original PDF, or private-content folder to the public GitHub repository.\n",
                encoding="utf-8")
            if ledger_path.read_bytes() != ledger_bytes:
                raise ValueError("Production ledger changed during extraction; review before finishing")
            temporary.rename(output)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "private-content")
    parser.add_argument("--ledger", type=Path, default=ROOT / "production/books" / f"{BOOK}.json")
    args = parser.parse_args()
    try:
        print(json.dumps(extract(args.pdf, args.output, args.ledger), indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Source recovery failed: {error}\n")


if __name__ == "__main__":
    main()
