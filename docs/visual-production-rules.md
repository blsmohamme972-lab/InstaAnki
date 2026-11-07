# Visual production rules

Status: production specification, version 1.1.0. Applies to every InstaAnki lesson. All narration, on-screen labels and questions are English. A full teaching lesson normally lasts 60–90 seconds.

## Core rules

1. **One tested idea per lesson.** Extract the learning objective from the source MCQ and its verified answer/explanation before designing the imagery.
2. **Use a clear metaphor or analogy.** Select a familiar visual comparison that explains the idea. Record the mapping between each important symbol and its medical meaning. Do not imply that a metaphor is literal anatomy.
3. **Create a distinctive visual mnemonic.** Use a small number of recognizable anchors. Keep recurring symbols, colors and meanings consistent across lessons.
4. **Use emotion and exaggeration deliberately.** Emphasize scale, expression, contrast or a surprising interaction to make the central idea memorable. Preserve the medical facts, sequence, direction and causal relationships. Exaggerated appearance must not imply unsupported probability, severity, urgency or dosage.
5. **Use stable memory-palace locations.** Assign an approved `locus_id` to the concept. Use persistent areas for Cardiac, Thoracic and Vascular Surgery and repeat the same landmark for the same concept across books. The palace layout organizes memory; it is not anatomical geography. A shared concept has a single canonical location or an explicitly recorded shared link.
6. **Keep the picture simple and readable.** Every object must contribute to the explanation or mnemonic. Give each narrated phrase one clear focal target. Keep English labels clear at phone size. Add exact labels, numbers and arrows as controlled overlays after image generation.
7. **Keep medical evidence accurate.** Validate anatomical relationships and factual diagrams against the source and suitable references. A mnemonic image is not a substitute for an authentic diagnostic image; label illustrative memory aids where confusion is possible.
8. **Plan the movement before rendering.** Write a storyboard that states what the viewer should see at each phrase, with image anchors, camera framing, spotlight target and keyframe timing.
9. **Use the voice-over as the master clock.** Derive camera, spotlight, captions and object states from audio playback time. Establish timing from the final audio, not estimated reading speed or independent timers. Editing or regenerating the voice-over invalidates the previous alignment until it is checked again.
10. **Make movement precise and purposeful.** Use explicit keyframes, bounded zoom, deliberate easing, stable endpoints and controlled transitions. Camera and spotlight follow the intended target without unrelated drift. The spotlight stays attached to its scene anchor during camera movement.
11. **Preserve synchronization during interaction.** Pause, seek and playback-speed changes must produce the correct scene state at the current audio time. Use deterministic rendering for these effects.
12. **Review the result on a phone.** Check the final audio, symbol meanings, labels, crop, focus target and synchronization at normal and accelerated playback. A lesson is complete only after its media and metadata pass review.

## Per-scene production record

Each scene records:

- `scene_id`, source question ID, source objective and canonical tag IDs.
- `locus_id` and the fixed landmark used for the concept.
- Image asset/version and symbol-to-meaning mappings.
- Final narration segment and aligned start/end times.
- Camera keyframes (scene coordinates, zoom, rotation if needed, duration and easing).
- Spotlight target anchor, shape, size, intensity and timed visibility.
- Exact English overlays and their timing.
- Whether an asset is a mnemonic illustration, a factual diagram or a licensed source image.
- Asset source, license and attribution where applicable.

Use scene coordinates for anchors, then transform them with the camera so highlights remain on the intended object. Simple movement can be rendered from still assets; Blender may produce selected 3D scenes in advance. Generative images supply assets, while controlled timeline code supplies precise camera and spotlight behavior.

## Production sequence

Source objective → medical check → mnemonic concept and stable locus → storyboard → images/3D assets → final voice-over → timing alignment → deterministic animation → MCQ and feedback → visual/audio review → content package.

## Illustration style and real-image ending

The initial reference direction is the visual-learning approach of Pixorize, Picmonic and Sketchy: original two-dimensional cartoon scenes, strong outlines, simple colors, expressive characters and a small set of deliberately mapped mnemonic objects. Reference the general learning approach; do not reuse another product's scenes, characters, logos or lesson artwork. Cinematic three-dimensional styling is optional when a specific lesson benefits from it, rather than the default.

Every lesson ends with one or more authentic images obtained from the web, such as a clinical photograph, angiogram or photomicrograph. Store each image locally with its source URL, author, license, attribution, image hash and an explanation of what it demonstrates. Choose a clear licensed source; personal use alone does not establish redistribution rights. Show the correct panel and preserve the original clinical meaning. Never label a generated mnemonic as a clinical photograph. Avoid implying that an illustrative clinical image is the exact patient or numerical scenario from the MCQ.

## Current pilot implementation

The three starter lessons have original two-dimensional mnemonic illustrations, locally generated English audio, an MCQ, and a nine-second real-image ending. Their 18 scenes now contain **55 measured narration phrases** linked to named visual targets. This replaces the earlier single spotlight anchor per scene. Kokoro ONNX synthesizes each phrase independently during production; neither the voice model nor a cloud voice service is needed on the phone. Runtime MP3 playback remains the master clock. These are measured phrase boundaries, **not forced word-level alignment** or estimates based on reading speed.

Each target supplies an exact arrow-tip point and an elliptical spotlight region on one identified image. The camera, spotlight and hand-arrow use the same image-fit and camera transform. The player holds the target while paused, resolves the correct target immediately after a seek, and follows the media clock at every playback speed. Reduced motion keeps the camera stationary while retaining the pointer and spotlight. Captions and controls use reserved space around the teaching image. A missing target, an incompatible image, or legacy content without guidance has no invented pointer.

Clinical images retain their full framing with camera zoom fixed at `1`. Each starter lesson also declares an `outroTargetId`: a calibrated, static point on its real image during the final nine seconds. The outro is part of the audio timeline, so pause, seek and playback-speed changes preserve its place before the MCQ. A clinical target must be justified by the source figure and visual inspection; an unlabelled or uncertain anatomical location remains unpointed.

### Named target and phrase records

The authoring source is `production/visual-guidance.json` (`schemaVersion: 1`). Coordinates refer to the **original image**, with the top-left at `(0, 0)` and bottom-right at `(1, 1)`, rather than to screen pixels or the image element's surrounding space.

| Field | Meaning |
| --- | --- |
| `images[path].sha256`, `width`, `height` | Exact image bytes and original dimensions used when inspecting its targets. |
| `targets[id].image`, `label` | Image path and concise English description of the visible feature or mnemonic mapping. |
| `targets[id].x`, `y` | Exact point touched by the arrow tip. The hand or arrow's center must not be substituted. |
| `targets[id].rx`, `ry` | Ellipse radii as fractions of original image width and height. The ellipse must remain inside the image and contain the arrow tip. |
| `targets[id].spotX`, `spotY` | Optional ellipse center, defaulting to `x`, `y`. Use this for a group: the four-lock cue points at an actual lock while its ellipse surrounds all four. |
| `targets[id].zoom` | Authored camera zoom from `1` to `1.25`; use `1` for clinical targets. |
| `scenes[].phrases[]` | Stable phrase `id`, verbatim `text`, and a named `targetId` or explicit `null`. Joining each scene's phrases with spaces must reproduce its approved narration exactly. |
| `outroTargetId` | Optional named target on the real image displayed during the final hold. |

Use `targetId: null` for explanations whose subject is absent from the picture, including abstract quantities or uncertain anatomical points. Do not highlight an unrelated object to fill time. Preserve the approved medical wording when dividing narration into phrases.

The generated timing companion records the sample rate, phrase and voice start/end sample indices, and corresponding playback seconds. It also binds the result to `audioSha256` and `visualGuidancePlanSha256`. `tools/guidance.py` checks these bindings, image hashes, target bounds, scene/phrase identities, complete narration, and measured cue continuity before assembly and production verification. Changing audio bytes invalidates old timing even when the recording's duration remains similar. Changing image bytes requires target review; changing the authoring plan requires regeneration before assembly.

### Authoring and regeneration

1. Inspect the original images and their source evidence. Update named targets, image hashes/dimensions, phrase divisions and the outro target in `production/visual-guidance.json`. Keep the source scripts and private book material in their established private locations.
2. Run `tools/generate_audio.py` with the local Kokoro model and voices. Its default guidance input is `production/visual-guidance.json`; `--guidance PATH` selects another plan. It derives phrase boundaries from actual synthesized samples and writes the MP3, timing companion and provenance together in the audio output directory.
3. Run `python tools/assemble_lessons.py` with the existing private source inputs available. Assembly uses `tools/guidance.py` to reject mismatched scripts, stale audio, changed images or an outdated plan, then embeds verified cues and targets in the public lesson data. Do not hand-edit assembled cue times as a substitute for regeneration.
4. Validate the pipeline and the actual player:

   ```sh
   python -m unittest discover -s tests -p 'test_guidance_pipeline.py'
   npm run test:guidance
   ```

   The Python checks cover measured timing and stale-media rejection. The browser checks compare rendered pointer and spotlight positions with the actual image bounds, including clinical framing, pause, seek, playback-rate changes, resizing, reduced motion, and delayed image loading. The browser command requires the project's Playwright dependency and its Chromium runtime.

Human listening and physical Android validation remain separate QA steps. For this revision, **`humanListeningReviewed: false` and `physicalAndroidTested: false`** remain explicit. Browser geometry checks, decoded audio and a successful Android build do not establish either of those checks.

