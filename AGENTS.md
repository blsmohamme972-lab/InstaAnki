# InstaAnki source instructions

- The active publication is the original 2015 Raja book already identified by `production/books/shahzad-raja-2015-200-practice-questions.json`.
- Read `production/source-policy.json`, `docs/SOURCE_SCOPE.md`, and the production workflow before producing or packaging lessons.
- Missing source evidence blocks new production. Do not substitute another book or independently authored collection, and do not relabel unrelated teaching material as a source question.
- A deliberate source-scope change requires an explicit user request and a reviewed policy change. Do not add a force flag or invent approval.
- New lessons require the actual question, choices, keyed answer, explanation and relevant figures. Compare the authored narration and quiz with the source before recording the sourceReview fingerprints.
- A copied sourceEvidence object or calculated hash does not constitute source review. Changed content needs a new actual comparison.
- Existing exact verified lessons can be replayed only through the pinned evidence checks. Count produced records truthfully and keep source identities stable.
- Keep all raw book material, source-recovery identifiers, annotations, private archives, keys and signing identity private and outside Git.
- Preserve learning records, notes and preferences when changing content.
- Run `npm run source:check` and source-policy/build regressions. Record visual, audio and browser checks honestly; physical-device and human-listening checks are separate.
