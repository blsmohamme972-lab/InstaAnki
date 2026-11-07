# Question tagging policy

Registry: `registry.v1.json` (version 1.0.0). All canonical labels and application-facing content are English.

## Three fixed specialties

- **Cardiac Surgery** includes adult and congenital cardiac subjects.
- **Thoracic Surgery** means general thoracic surgery within InstaAnki.
- **Vascular Surgery** covers the vascular subject areas defined by the registry.

Every publishable question has exactly one primary specialty, one primary domain and one learning focus. Optional secondary specialties require actual overlap in the tested reasoning. A tag being eligible for several specialties does not assign all of them automatically.

## Detailed, controlled facets

Use separate fields for domain, condition, procedure, anatomy, learning focus, perioperative phase and population. Store canonical IDs, not free-form hashtags. Display readable labels; derive parent categories for browsing. The initial 118 entries are a starting vocabulary, not an exhaustive syllabus.

Read the stem, keyed answer and available explanation together. Respect negation, EXCEPT wording and the actual task; the keyed option alone may not describe the entire learning objective. Write one short tested-objective statement, then select the smallest sufficient set of tags. Never tag a disease solely because it appears as a distractor or incidental history. Do not infer a disease subtype, operation, anatomical site, severity or age group that the source does not support.

Aortic disease has shared domain and condition IDs across Cardiac and Vascular Surgery. The word "thoracic" in "thoracic aorta" does not route the question to general Thoracic Surgery. Congenital disease does not by itself imply a pediatric patient.

Use aliases to find canonical IDs. For example, CABG resolves to Coronary Artery Bypass Grafting. Do not perform global substitutions for ambiguous abbreviations such as AS or MS.

## Annotation and validation

`annotation.schema.json` checks the record shape and allowed IDs. Semantic checks additionally require:

1. Selected IDs are active and primary/secondary lists do not repeat each other.
2. The primary domain supports the primary specialty; any other scope mismatch is reviewed rather than silently forced.
3. Each selected ID has a concise source-grounded reason.
4. Evidence supports the specific condition/procedure and the tested learning focus.
5. Unresolved answer/extraction conflicts and missing concepts remain `needs_review` and block lesson publication.
6. Prefer the most specific supported condition; do not store its ancestor as a second condition merely to enable category search.

`examples.json` contains three synthetic examples only. It does not report progress on the uploaded book and does not assert any clinical answer.

## Fixed identities across books and updates

The same concept uses the same ID in every book, question and lesson. A lesson references its source question's annotation. Store book title, edition, page and source question number separately as provenance.

Do not put production status or learner state (Due, Forgotten, Difficult, accuracy) into the clinical taxonomy. Updating an annotation must preserve question identity, lesson identity, comments and FSRS history. Matching tags do not prove two questions are duplicates.

New concepts enter through a reviewed, versioned registry update after checking aliases and scope. IDs are never recycled. Label improvements preserve old labels as aliases. Merges and splits require explicit deprecation/replacement mappings, with prior registries retained for existing packs. Record the registry version and annotation revision on every record.

## Smart behavior

The app can filter an entire specialty or a specific condition/procedure, retrieve related lessons across books, and summarize learning performance by tag. Related-content suggestions must respect the SRS due queue and the daily new-content limit; a tag or like is not evidence of successful recall.

Stable clinical tags also identify reusable memory-palace locations. Visual changes must not silently remap an established location. See [visual production rules](../docs/visual-production-rules.md).

## Scope references

These official sources inform broad coverage; this registry is an InstaAnki design, not an official syllabus or endorsed taxonomy:

- [ABTS Written Exam Blueprint](https://www.abts.org/ABTS/CertificationWebPages/Exam_Sequence/Written_Exam_Blueprint.aspx)
- [ABS Vascular Surgery Overview](https://www.absurgery.org/get-certified/vascular-surgery/)
- [ABS Vascular Surgery EPAs](https://www.absurgery.org/get-certified/epas/vascular-surgery/)
