# Question tagging policy

Current registry: `registry.latest.json` (version 1.1.0), identical to the immutable `registry.v1.1.json` snapshot. All canonical labels and application-facing content are English.

## Versions and loading

| Registry version | Immutable registry | Annotation schema |
|---|---|---|
| 1.0.0 | `registry.v1.json` | `annotation.v1.schema.json` |
| 1.1.0 | `registry.v1.1.json` | `annotation.v1.1.schema.json` |

`annotation.schema.json` is the latest schema alias. Load the immutable registry and schema named by a content pack's `taxonomy_version`; do not validate an older pack against an unrelated latest-version schema. The latest aliases are convenience copies for authoring new content. The original 1.0.0 registry is preserved byte for byte.

Version 1.1.0 is additive: it introduces six entries and the optional `concept_ids` facet. See `migration.v1.0-to-v1.1.json` for the explicit migration contract and snapshot hashes. Existing annotations remain valid against their original registry; updating the registry alone does not retag questions or change review history.

## Three fixed specialties

- **Cardiac Surgery** includes adult and congenital cardiac subjects.
- **Thoracic Surgery** means general thoracic surgery within InstaAnki.
- **Vascular Surgery** covers the vascular subject areas defined by the registry.

Every publishable question has exactly one primary specialty, one primary domain and one learning focus. Optional secondary specialties require actual overlap in the tested reasoning. A tag being eligible for several specialties does not assign all of them automatically.

## Detailed, controlled facets

Use separate fields for domain, condition, procedure, concept, anatomy, learning focus, perioperative phase and population. Store canonical IDs, not free-form hashtags. Display readable labels; derive parent categories for browsing. Version 1.1.0 has 124 entries, extending the initial 118-entry vocabulary; neither is an exhaustive syllabus.

The optional `concept_ids` facet describes tested principles that are not diagnoses or procedures, such as Coronary Dominance and Poiseuille's Law. Its absence means an empty list. Vascular Physiology covers pressure, flow and resistance without implying Peripheral Arterial Disorders. Choose its primary specialty from the tested context; eligibility for several specialties does not require storing all of them.

Read the stem, keyed answer and available explanation together. Respect negation, EXCEPT wording and the actual task; the keyed option alone may not describe the entire learning objective. Write one short tested-objective statement, then select the smallest sufficient set of tags. Never tag a disease solely because it appears as a distractor or incidental history. Do not infer a disease subtype, operation, anatomical site, severity or age group that the source does not support.

Aortic disease has shared domain and condition IDs across Cardiac and Vascular Surgery. The word "thoracic" in "thoracic aorta" does not route the question to general Thoracic Surgery. Congenital disease does not by itself imply a pediatric patient.

Use aliases to find canonical IDs. For example, CABG resolves to Coronary Artery Bypass Grafting. Do not perform global substitutions for ambiguous abbreviations such as AS or MS.

## Annotation and validation

`annotation.schema.json` checks the record shape and allowed IDs. Semantic checks additionally require:

1. Selected IDs are active and primary/secondary lists do not repeat each other.
2. The primary domain supports the primary specialty; any other scope mismatch is reviewed rather than silently forced.
3. Each selected ID has a concise source-grounded reason.
4. Evidence supports the specific condition, procedure or concept and the tested learning focus.
5. Unresolved answer/extraction conflicts and missing concepts remain `needs_review` and block lesson publication.
6. Prefer the most specific supported condition; do not store its ancestor as a second condition merely to enable category search.

`examples.json` contains six synthetic examples only, including coronary dominance, the extralobar pleural relationship and vascular physiology. It contains no source-book question text, reports no production progress and asserts no patient-specific clinical answer. The original three 1.0.0 examples remain in `examples.v1.json`.

Every ID in `concept_ids`, like every other selected ID, needs an evidence entry. An evidence record must refer to the stem, keyed answer or explanation; a distractor alone cannot justify a tag. A specific condition's parent remains available through the registry hierarchy without duplicating it in `condition_ids`.

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

The 1.1.0 additions also use these sources for the narrow anatomical or physiological terms:

- [Coronary dominance definition and angiographic example](https://link.springer.com/article/10.1134/S1064562424602026)
- [Extralobar sequestration with a separate visceral pleural covering](https://link.springer.com/article/10.1186/s43055-021-00440-1)
- [Poiseuille resistance equation and its idealized flow assumptions](https://openstax.org/books/university-physics-volume-1/pages/14-7-viscosity-and-turbulence)
