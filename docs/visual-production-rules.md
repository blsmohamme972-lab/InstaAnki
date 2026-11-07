# Visual production rules

Status: production specification, version 1.0.0. Applies to every InstaAnki lesson. All narration, on-screen labels and questions are English. A full teaching lesson normally lasts 60–90 seconds.

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

The local voice-generation engine remains undecided, as requested. This specification does not claim that images, audio, videos or the Android renderer have already been produced.
