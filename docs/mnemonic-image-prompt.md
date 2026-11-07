# Mnemonic image master prompt and approval checkpoint

Specification version: **2.0.0**. Use this guide together with [visual-production-rules.md](visual-production-rules.md). It replaces the vague instruction to make a beautiful memory-palace picture. Updating this guide does not authorize any new image, video or lesson production.

## Master instruction for the authoring agent

> Before writing or sending a mnemonic image prompt, open and study **all three** references: **[Pixorize](https://pixorize.com/), [Picmonic](https://www.picmonic.com/), and [Sketchy](https://www.sketchy.com/)**. Inspect their actual public artwork or a usable scene from an official video, as well as their explanation of the method. Record what you actually saw and how it informs this lesson. Merely naming the sites, visiting a homepage, reading a search summary, or viewing an unreadable thumbnail does not satisfy this step.
>
> Build an original **2D cartoon visual mnemonic story** using the studied approach: distinctive expressive characters, strong visual puns or intuitive associations, exaggerated teaching props, purposeful actions, and a stable spatial setting. Every teaching symbol must lead back to an exact verified fact from the approved source. The characters and objects must participate in one memorable event; attractive scenery alone is insufficient.
>
> Before any generator call, complete the fact-to-symbol/action map, art brief, exact final prompt and required review below. Resolve every failed check, then pass the local prompt gate. Send only the exact approved prompt from its ready artifact. Inspect the generated result afterward; approval of the prompt does not approve the image automatically.

The **authoring agent** performs this research. Adding URLs to an image-generator prompt does not establish that the generator browsed or understood those sites. Translate the observations into concrete visual instructions. If a supported generator can receive a permitted reference image, document that actual input separately; do not claim an attachment was supplied when it was not.

## Required reference study

| Provider | Official method page | What to study and record |
| --- | --- | --- |
| Pixorize | [Anatomy of a Pixorize Video](https://blog.pixorize.com/2024/04/26/anatomy-of-a-pixorize-video/) | How selected facts become sound-alike symbols and a coherent story; how symbol visibility, crowding and the viewer's gaze shape the art. Inspect an actual illustration on the page or a linked official example. |
| Picmonic | [Educator guide to visual mnemonics](https://www.picmonic.com/pages/educators-engage-students-in-the-classroom-with-visual-mnemonics/) | How phonetic keyword characters and their exaggerated props connect through a narrative. Inspect the actual character artwork and explain the recall cue, rather than copying it. |
| Sketchy | [Visual memory and elaborative encoding](https://www.sketchy.com/blog/visual-memory-and-elaborative-encoding) | How memorable symbols, a familiar location, proximity, color and story support a narrated tour. Inspect a usable scene from an official public illustration or video. |

For each provider, record the official page URL, exact example URL, visible connection between them, inspection time, inspection scope, concrete visual observations and the method applied to this lesson. Scope must be a complete scene, an actual video scene, or a readable character example. A promotional thumbnail does not count as a full scene or watched video.

Use legitimate accessible public examples. Localhost, private-network addresses and reserved example hosts do not count as public visual references. Respect access restrictions; do not bypass a login, paywall or security block. If one example is unavailable, a different independently available official example may be used with its own truthful record. If no adequate example is accessible, leave that provider pending and block image generation. A user-supplied reference can help resolve access, but it must be actually inspected and its provenance resolved before a gate review is approved.

**Reference-review status for this specification update:** actual Pixorize illustrations and Picmonic character artwork were inspected. Sketchy's official method article and an independently available official embedded-video thumbnail were inspected; a full example asset was blocked in the browser. The thumbnail is limited evidence and is **not** an approved future-production reference review. No lesson-specific review or generator approval is created by this document.

The method summaries above are grounded in the linked official sources. The portrait layout, restrained shading and review checklist below are InstaAnki's implementation requirements. These websites inform visual teaching; the original Raja book remains the authorized medical source.

## Build the brief before the final prompt

1. **Verify the lesson.** Confirm the original book, exact source question, keyed answer, explanation and referenced figures. Complete the existing source review. Do not use a reference company's medical lesson as a substitute source.
2. **Select the tested idea.** State one objective. Retain the source's qualifying language; the mnemonic must not turn an association into causation, a typical feature into an absolute rule, or a numerical threshold into an invented visual claim.
3. **Map the teaching symbols.** For every symbol, record the exact fact, its mnemonic recall cue, its action or relationship, its position, and the narration phrase that explains it. Prefer a clear sound-alike, a familiar semantic association or an action that expresses the verified relationship. Arbitrary decoration or color alone is insufficient. Reuse established symbols only when their meanings match; do not pretend a global symbol registry exists when none has been maintained.
4. **Write one story.** Describe what the characters are doing and why the objects belong together. Use deliberate exaggeration and expression. The story may be playful or absurd, but the facts it encodes must remain accurate. Remove props that have no teaching or necessary setting purpose.
5. **Use the locus purposefully.** Keep the canonical concept location stable. It can be a specific workbench, dock, café or other familiar scene. A memory location does not require an ornate palace. Explain how the location supports the story and the narrated route.
6. **Plan the phone composition.** Compose a portrait image from the start. Give each focal symbol a clear silhouette, enough separation for a spotlight, and a visible action. Place teaching targets outside the app's actual caption/control/MCQ overlap regions. Keep required anatomy or meaning-bearing props uncropped. Use a quiet supporting background, crisp dark contours, distinct local colors and restrained 2D shading.
7. **Separate precise overlays.** Reserve space for exact English text, numbers, labels, arrows and recap diagrams to be added by controlled code. The generated artwork must not be relied upon for accurate labels or numerical facts.

The selected private draft lesson must contain its existing `locus`, `mnemonicSymbols`, source evidence and reviewed teaching content, plus:

```json
{
  "artBrief": {
    "schemaVersion": 1,
    "rendering": "2d-mnemonic-cartoon",
    "objective": "One verified source objective, written in full.",
    "story": "One coherent event connecting all teaching symbols.",
    "styleNotes": "Concrete 2D visual qualities learned from the inspected examples.",
    "composition": "Portrait framing, focal hierarchy, symbol positions and actual overlay space.",
    "locusUse": "The stable concept location and how it supports this particular story.",
    "overlayPlan": "Exact information to add separately with controlled overlays.",
    "symbolActions": [
      {
        "symbol": "Exact symbol name from mnemonicSymbols",
        "meaning": "Exact corresponding meaning from mnemonicSymbols",
        "recallCue": "Why this appearance or wordplay recalls the verified fact.",
        "action": "What this character or prop does in the story.",
        "position": "Its visible position and relationship to the other symbols.",
        "narrationCue": "The approved narration phrase explaining the mapping."
      }
    ]
  },
  "imagePrompt": "The fully resolved final prompt, not this example or an unfilled template."
}
```

`symbolActions` must cover every `mnemonicSymbols` entry exactly once with matching symbol names and meanings. The gate binds the complete brief, including additional fields. The snippets in this guide illustrate structure; they are not lesson drafts or approved reviews.

## Final generator prompt template

Replace every `{{...}}` field with the reviewed lesson-specific detail. The gate rejects these explicit unfilled markers. Do not send this unfilled template. Do not copy the websites' particular scenes, characters, logos or artwork; create an original composition using the studied visual mnemonic method.

```text
Create one original portrait 2D cartoon educational mnemonic illustration.

VISUAL DIRECTION
Use the visual mnemonic storytelling approach studied in Pixorize,
Picmonic and Sketchy: expressive characters, memorable visual puns,
exaggerated teaching props, purposeful interactions and a coherent setting.
Draw crisp dark outlines, strong readable silhouettes, bright distinguishable
local colors and restrained cel-like shading. Keep the background supportive
and quieter than the teaching symbols. The scene must read clearly on a phone.

VERIFIED TEACHING OBJECTIVE
{{Exact approved objective; no additional medical claims.}}

ONE COHERENT STORY
{{Describe the event and how the characters/props interact. Each action must
support the intended fact or mnemonic association.}}

SYMBOLS AND ACTIONS
{{For each symbol: exact appearance; verified fact it represents; recall cue;
specific action; position; relationship to the other symbols.}}
Every teaching symbol must remain distinct and easy to locate. Preserve the
specified relationships and meanings. Do not invent additional teaching props.

STABLE MEMORY LOCATION
{{Describe the approved locus and its recognizable landmark. Explain the
setting in concrete visual terms; architecture must not dominate the symbols.}}

PORTRAIT COMPOSITION
{{Specify the aspect ratio, primary focal target, secondary targets, narrated
viewing route, separations, margins and app-overlay regions.}}
Keep meaning-bearing objects and all required interactions fully visible.

OVERLAY SPACE
{{Describe blank/quiet areas reserved for controlled text, numbers and arrows.}}
Do not draw letters, words, numbers, captions, labels, arrows, logos or watermarks.

EXCLUDE
Photorealism, glossy 3D rendering, cinematic depth of field, ornamental palace
scenery, decorative clutter, generic stock-medical imagery, isolated unrelated
props, unsupported medical implications, and copies of reference-brand scenes.
```

## Required review: every check must pass

Review the **complete final prompt and brief**, not just its opening style paragraph. Record the actual reviewer, time, specific observations and unresolved concerns. Use a second reviewer/agent when available. Do not label an agent review as user approval, clinician review or human inspection.

| Required check | Pass only when |
| --- | --- |
| `sourceAligned` | The objective, all fact/symbol mappings, actions and spatial implications match the reviewed original source. |
| `allThreeReferencesVisuallyInspected` | Usable actual examples from all three providers were inspected and individually documented; no blocked, pending or thumbnail-only record is treated as complete. |
| `symbolMeaningsExplicit` | Every teaching symbol has one explicit meaning and an understandable recall cue. |
| `storyAndInteractionsClear` | The prompt describes one coherent event and purposeful character/object interactions, with no unexplained collection of props. |
| `originalComposition` | The characters, scene and arrangement are original applications of the reference methods. |
| `twoDimensionalCartoon` | The exact prompt consistently calls for the specified 2D outlined cartoon artwork without conflicting glossy/cinematic/3D instructions. |
| `phoneReadable` | Portrait framing, focal hierarchy, symbol separation and app-overlay space are explicit. |
| `noDecorativeFiller` | The background supports recall and does not overwhelm the teaching characters or add unmapped distracting props. |
| `locusSupportsStory` | The stable location is meaningful and consistent; literal palace architecture is not used as a substitute for a story. |
| `exactOverlaysSeparated` | Precise text, numbers, arrows and diagrams are planned separately; the image model is not responsible for factual lettering. |

Any failed or uncertain item means **revise before generation**. Do not average a failure into a passing score or tick every box automatically. No placeholders, unresolved choices or contradictory style instructions may remain in the exact generator prompt.

## Run the pre-generation gate

Only do this for production explicitly authorized by the user and allowed by the existing source policy. Select one lesson from its private draft. Both commands validate its source and brief; neither changes a production ledger.

```bash
python3 tools/prepare_image_prompt.py \
  --input private-content/lesson-draft.json \
  --lesson LESSON_ID \
  --fingerprint
```

This prints request-binding metadata only. It does **not** create a review, approve anything, or call an image generator. After the actual review, record a private JSON review with:

- `schemaVersion: 1`, the exact `lessonId` and computed `requestSha256`.
- The real `reviewer`, timezone-aware `reviewedAt`, meaningful `notes`, and `decision: "approved"` only after the checks pass.
- `references`: exactly one record for each provider, with `provider` (`Pixorize`, `Picmonic`, or `Sketchy`), official `pageUrl`, exact `exampleUrl`, `exampleKind` (`image`, `video`, or `page-artwork`), `inspectionScope` (`complete-scene`, `video-scene`, or `character-example`), `linkedFromPage` equal to the official page URL, and specific `linkEvidence` describing the observed page-to-example connection.
- Each reference also records `access: "public"`, `inspectionStatus: "inspected"`, the real timezone-aware `inspectedAt`, concrete `observations`, and lesson-specific `appliedMethod`. Inspection must precede approval. External video/CDN URLs require the explicit official-page connection; a lookalike domain is not an official provider.
- A `checks` object containing all ten keys in the table, set to true only after the work actually occurred. A pending review must keep its failed checks false and must not use an approved decision.

Then validate and export:

```bash
python3 tools/prepare_image_prompt.py \
  --input private-content/lesson-draft.json \
  --lesson LESSON_ID \
  --review private-content/image-prompt-review.json \
  --output private-content/ready-image-request.json \
  --emit
```

The successful output is one atomically written JSON object containing the **exact `prompt`** and its **`receipt`**. Inside the repository, output must be under the ignored `private-content/` directory; public/runtime/build destinations and symlink aliases through those public trees are rejected. An external authoring workspace is supported, including a `private-content/` link to that workspace, but the agent must actually choose a private location: the tool cannot certify an arbitrary external directory's sharing permissions.

Choose a new output filename for each approved revision; the tool refuses to overwrite an existing artifact. Send that prompt unchanged to the generator. Keep the artifact private and retain it with the production provenance. There is no force or auto-approval option. Failure produces no new ready artifact and leaves the source ledger unchanged; an older artifact must never be reused after a failed run.

The binding covers the exact prompt, full art brief, mnemonic symbols, locus, source evidence, reviewed teaching-content fingerprints, source review and the bytes of both visual-specification documents. Any change requires a fresh review and gate run. Prompt/symbol changes cannot rely on the older source-review fingerprint, which intentionally serves a different purpose.

This tool verifies the presence, structure and freshness of recorded reviews. It does not prove that a reviewer browsed the sites, replace clinical judgment, score artwork, call the generator, or intercept an external image tool. The mandatory agent workflow in `AGENTS.md` provides that execution contract. Actual generated-image inspection, source validation, lossless image optimization, timing review and final lesson QA remain required afterward.

The gate is specific to new or regenerated mnemonic artwork. Do not add it as a blanket prerequisite to unchanged historical media replay or audio-only fixes. Never fabricate old prompt reviews or require an old APK/ZIP merely to author a new prompt.
