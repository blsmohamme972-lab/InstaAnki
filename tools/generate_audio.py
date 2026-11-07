#!/usr/bin/env python3
"""Render local English narration with sample-derived phrase and scene timestamps.

Requires Python packages kokoro-onnx, onnxruntime, numpy and soundfile, plus
ffmpeg/ffprobe. Models stay outside the repository. No network calls are made.

Example:
    python tools/generate_audio.py --model /path/kokoro-v1.0.onnx \
        --voices /path/voices-v1.0.bin

The audio includes the final real-image hold. Its playback clock can therefore
drive the entire lesson, including pause, seek and playback-speed changes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timezone

from guidance import canonical_hash, validate_plan
from source_policy import SourcePolicy, SourcePolicyError


PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT.parent / "runtime"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
SAFE_AUDIO_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def validate_audio(samples: np.ndarray, name: str) -> dict:
    import numpy as np
    if samples.ndim != 1 or not samples.size:
        raise ValueError(f"{name}: empty or non-mono audio")
    if not np.isfinite(samples).all():
        raise ValueError(f"{name}: non-finite samples")
    peak = float(np.abs(samples).max())
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if peak < 0.001 or rms < 0.0001:
        raise ValueError(f"{name}: silence or unexpectedly low level")
    return {"finite": True, "peak": peak, "rms": rms,
            "samplesAtOrAboveFullScale": int(np.count_nonzero(np.abs(samples) >= 1.0))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PROJECT / "private-content/starter-lessons-draft.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "web/media/audio")
    parser.add_argument("--guidance", type=Path, default=PROJECT / "production/visual-guidance.json")
    parser.add_argument("--model", type=Path, default=RUNTIME / "tts/kokoro-v1.0.onnx")
    parser.add_argument("--voices", type=Path, default=RUNTIME / "tts/voices-v1.0.bin")
    parser.add_argument("--cache", type=Path, default=RUNTIME / "tts-cache")
    parser.add_argument("--voice", default="af_sarah")
    parser.add_argument("--speed", type=float, default=0.96)
    parser.add_argument("--outro", type=float, default=9.0)
    parser.add_argument("--gap", type=float, default=0.23)
    parser.add_argument("--phrase-gap", type=float, default=0.08)
    parser.add_argument("--threads", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--lesson", action="append", help="Generate only this lesson ID; repeatable.")
    parser.add_argument("--force", action="store_true", help="Regenerate cached scene audio.")
    args = parser.parse_args()
    policy = SourcePolicy(PROJECT)
    if not args.input.is_file():
        # Give the actionable source error even on a clean checkout with no TTS.
        policy.source_records(policy.ledger())
        parser.error(f"Required authoring file does not exist: {args.input}")
    if not 0.9 <= args.speed <= 1.0:
        parser.error("Use a speed between 0.90 and 1.00 for these narration scripts.")
    if not 8.0 <= args.outro <= 10.0:
        parser.error("The final real-image stage must last 8–10 seconds.")
    if not 0.0 <= args.gap <= 0.5 or not 0 <= args.phrase_gap <= 0.25 or args.threads < 1:
        parser.error("Gap must be 0–0.5 seconds and thread count must be positive.")

    draft = json.loads(args.input.read_text())
    if (not isinstance(draft, dict) or not isinstance(draft.get("lessons"), list)
            or any(not isinstance(lesson, dict) or not isinstance(lesson.get("id"), str) for lesson in draft["lessons"])):
        parser.error("Narration input must contain a source-bound lessons array with stable IDs.")
    known_ids = [lesson["id"] for lesson in draft["lessons"]]
    if len(set(known_ids)) != len(known_ids):
        parser.error("Narration input has duplicate audio lesson IDs.")
    if args.lesson and (len(set(args.lesson)) != len(args.lesson) or set(args.lesson) - set(known_ids)):
        parser.error("Every --lesson must name an existing audio lesson exactly once.")
    lessons = [lesson for lesson in draft["lessons"]
               if not args.lesson or lesson["id"] in args.lesson]
    if not lessons:
        parser.error("No matching lessons.")
    policy.validate_audio_authoring(draft, lessons)
    for path in (args.model, args.voices, args.guidance):
        if not path.is_file():
            parser.error(f"Required file does not exist: {path}")
    guidance_document = json.loads(args.guidance.read_text())
    if guidance_document.get("schemaVersion") != 1:
        parser.error("Unsupported visual guidance plan schema")
    guidance_plans = {item["audioLessonId"]: item for item in guidance_document["lessons"]}
    if len(guidance_plans) != len(guidance_document["lessons"]):
        parser.error("Guidance audioLessonId values must be unique")
    for lesson in lessons:
        if not SAFE_AUDIO_ID.fullmatch(lesson["id"]):
            parser.error(f"Unsafe audio lesson ID: {lesson['id']}")
        plan = guidance_plans.get(lesson["id"])
        if plan is None:
            parser.error(f"No reviewed visual guidance plan for {lesson['id']}")
        if plan.get("id") != lesson.get("lessonId", lesson["id"]):
            parser.error("Guidance and narration must retain the same canonical app lessonId.")
        validate_plan(plan, lesson["scenes"], PROJECT / "web")
    # Import and initialize the costly speech runtime only after source checks.
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)

    engine_version = importlib.metadata.version("kokoro-onnx")
    model_hash = sha256(args.model)
    voices_hash = sha256(args.voices)
    print("Loading local Kokoro model on CPU", flush=True)
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = args.threads
    session_options.inter_op_num_threads = 1
    session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(args.model), sess_options=session_options,
                                  providers=["CPUExecutionProvider"])
    engine = Kokoro.from_session(session, str(args.voices))
    if args.voice not in engine.get_voices():
        parser.error(f"Voice is not present in the local voice file: {args.voice}")

    provenance_path = args.output / "audio-provenance.json"
    old_provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
    rendered = {item["lessonId"]: item for item in old_provenance.get("lessons", [])}
    provenance = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "engine": "kokoro-onnx",
        "engineVersion": engine_version,
        "onnxruntimeVersion": ort.__version__,
        "executionProvider": "CPUExecutionProvider",
        "localSynthesis": True,
        "voice": args.voice,
        "language": "en-us",
        "speed": args.speed,
        "model": {"filename": args.model.name, "sha256": model_hash, "sourceUrl": MODEL_URL},
        "voices": {"filename": args.voices.name, "sha256": voices_hash, "sourceUrl": VOICES_URL},
        "inputSha256": sha256(args.input),
        "alignment": "Exact sample boundaries of independently synthesized target phrases; no estimated word timing.",
        "phraseGapSeconds": args.phrase_gap,
        "guidancePlanSha256": sha256(args.guidance),
        "humanListeningReviewed": False,
        "automatedChecks": ["Nonempty mono audio", "Finite samples", "Non-silent narration",
                            "Decoded MP3 below full scale", "60–90 second total duration",
                            "8–10 second final real-image stage", "Container and PCM durations agree"],
    }

    for lesson in lessons:
        lesson_id = lesson["id"]
        print(f"Rendering {lesson_id}", flush=True)
        plan = guidance_plans.get(lesson_id)
        if plan is None:
            raise ValueError(f"No reviewed visual guidance plan for {lesson_id}")
        validate_plan(plan, lesson["scenes"], PROJECT / "web")
        segments = []
        sample_rate = None
        for scene, planned_scene in zip(lesson["scenes"], plan["scenes"]):
            text = scene["voice_text"].strip()
            spoken_text = scene.get("spoken_text", text).strip()
            phrases = []
            for phrase in planned_scene["phrases"]:
                cache_input = {"text": phrase["text"], "voice": args.voice, "speed": args.speed,
                               "language": "en-us", "engineVersion": engine_version,
                               "modelSha256": model_hash, "voicesSha256": voices_hash,
                               "sentencePause": 0.25, "clausePause": 0.1}
                cache_key = hashlib.sha256(json.dumps(cache_input, sort_keys=True).encode()).hexdigest()
                cache_file = args.cache / f"{cache_key}.wav"
                if cache_file.exists() and not args.force:
                    samples, sr = sf.read(cache_file, dtype="float32")
                    print(f"  {phrase['id']}: cached {len(samples) / sr:.2f}s", flush=True)
                else:
                    samples, sr = engine.create(phrase["text"], voice=args.voice, speed=args.speed,
                                                lang="en-us", sentence_pause=0.25, clause_pause=0.1)
                    samples = np.asarray(samples, dtype=np.float32)
                    validate_audio(samples, f"{lesson_id}/{phrase['id']}")
                    sf.write(cache_file, samples, sr, subtype="FLOAT")
                    print(f"  {phrase['id']}: synthesized {len(samples) / sr:.2f}s", flush=True)
                validate_audio(samples, f"{lesson_id}/{phrase['id']}")
                if sample_rate is not None and sample_rate != sr:
                    raise ValueError("Sample rate changed between phrases")
                sample_rate = sr
                phrases.append((phrase, samples))
            segments.append((scene, text, spoken_text, phrases))

        sample_rate = int(sample_rate)
        lead_samples = round(0.18 * sample_rate)
        gap_samples = round(args.gap * sample_rate)
        phrase_gap_samples = round(args.phrase_gap * sample_rate)
        tail_samples = round(0.35 * sample_rate)
        parts = [np.zeros(lead_samples, dtype=np.float32)]
        cursor = lead_samples
        scene_timings, cue_timings = [], []
        for index, (scene, text, spoken_text, phrases) in enumerate(segments):
            start_sample = 0 if index == 0 else cursor
            voice_start_sample = cursor
            for phrase_index, (phrase, samples) in enumerate(phrases):
                cue_start_sample = start_sample if phrase_index == 0 else cursor
                cue_voice_start = cursor
                parts.append(samples)
                cursor += len(samples)
                cue_voice_end = cursor
                if phrase_index == len(phrases) - 1:
                    pause_samples = tail_samples if index == len(segments) - 1 else gap_samples
                else:
                    pause_samples = phrase_gap_samples
                parts.append(np.zeros(pause_samples, dtype=np.float32))
                cursor += pause_samples
                cue_timings.append({
                    "id": phrase["id"], "sceneId": scene["id"],
                    "text": phrase["text"], "targetId": phrase.get("targetId"),
                    "start": cue_start_sample / sample_rate, "end": cursor / sample_rate,
                    "voiceStart": cue_voice_start / sample_rate, "voiceEnd": cue_voice_end / sample_rate,
                    "startSample": cue_start_sample, "endSample": cursor,
                    "voiceStartSample": cue_voice_start, "voiceEndSample": cue_voice_end,
                })
            scene_timings.append({
                "id": scene["id"], "start": start_sample / sample_rate,
                "end": cursor / sample_rate, "duration": (cursor - start_sample) / sample_rate,
                "voiceStart": voice_start_sample / sample_rate,
                "voiceEnd": cue_voice_end / sample_rate,
                "startSample": start_sample, "endSample": cursor,
                "voiceStartSample": voice_start_sample, "voiceEndSample": cue_voice_end,
                "text": text, "spokenText": spoken_text,
            })
        narration_samples = cursor
        outro_samples = round(args.outro * sample_rate)
        parts.append(np.zeros(outro_samples, dtype=np.float32))
        cursor += outro_samples
        timeline_duration = cursor / sample_rate
        if not 60.0 <= timeline_duration <= 90.0:
            raise ValueError(f"{lesson_id}: {timeline_duration:.3f}s is outside 60–90s. "
                             "Adjust speed or the reviewed script; do not pad with excess silence.")
        audio = np.concatenate(parts)
        raw_check = validate_audio(audio, lesson_id)
        # Leave codec headroom; never increase an already quiet source.
        gain = min(1.0, 0.89 / raw_check["peak"])
        audio *= gain
        pcm_check = validate_audio(audio, lesson_id)
        audio_path = args.output / f"{lesson_id}.mp3"
        with tempfile.TemporaryDirectory(prefix=f"{lesson_id}-", dir=args.cache) as temporary:
            wav_path = Path(temporary) / "narration.wav"
            decoded_path = Path(temporary) / "decoded.wav"
            sf.write(wav_path, audio, sample_rate, subtype="PCM_24")
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(wav_path), "-c:a", "libmp3lame", "-b:a", "96k",
                            "-ar", str(sample_rate), "-ac", "1", "-write_xing", "1",
                            "-metadata", f"title={lesson['title']}", str(audio_path)], check=True)
            probe = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(audio_path)]))
            container_duration = float(probe["format"]["duration"])
            if not math.isclose(container_duration, timeline_duration, abs_tol=0.1):
                raise ValueError(f"Container/PCM duration mismatch: {container_duration} vs {timeline_duration}")
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(audio_path), "-c:a", "pcm_f32le", str(decoded_path)], check=True)
            decoded, decoded_sr = sf.read(decoded_path, dtype="float32")
            decoded_check = validate_audio(decoded, f"Decoded {lesson_id}")
            if decoded_sr != sample_rate or decoded_check["samplesAtOrAboveFullScale"]:
                raise ValueError(f"Decoded audio failed sample-rate/clipping check: {lesson_id}")
            # Allow codec padding; the container edit list determines playback duration.
            if abs(len(decoded) / decoded_sr - timeline_duration) > 0.1:
                raise ValueError(f"Unexpected codec padding: {lesson_id}")
        timing = {
            "schemaVersion": 2, "lessonId": lesson_id,
            "audioPath": f"/media/audio/{audio_path.name}",
            "audioSha256": sha256(audio_path),
            "visualGuidancePlanSha256": canonical_hash(plan),
            "alignment": "independently-synthesized-phrase-samples",
            "sampleRate": sample_rate, "totalSamples": cursor,
            "duration": timeline_duration, "containerDuration": container_duration,
            "narrationDuration": narration_samples / sample_rate,
            "sourceNarrationSha256": hashlib.sha256("\n".join(s[1] for s in segments).encode()).hexdigest(),
            "scenes": scene_timings, "cues": cue_timings,
            "realImageOutro": {"start": narration_samples / sample_rate, "end": timeline_duration,
                               "duration": outro_samples / sample_rate,
                               "startSample": narration_samples, "endSample": cursor,
                               "imagePath": lesson["real_image_path"],
                               "audioIncluded": True},
            "mcqStartsAt": timeline_duration,
        }
        write_json(args.output / f"{lesson_id}.timing.json", timing)
        rendered[lesson_id] = {
            "lessonId": lesson_id, "audioFile": audio_path.name,
            "timingFile": f"{lesson_id}.timing.json", "sha256": sha256(audio_path),
            "bytes": audio_path.stat().st_size, "duration": timeline_duration,
            "containerDuration": container_duration, "narrationDuration": narration_samples / sample_rate,
            "outroDuration": args.outro, "sampleRate": sample_rate,
            "normalizationGain": gain, "sourcePeakBeforeGain": raw_check["peak"],
            "pcmValidation": pcm_check, "decodedValidation": decoded_check,
            "humanListeningReviewed": False, "cueCount": len(cue_timings),
        }
        provenance["lessons"] = list(rendered.values())
        write_json(provenance_path, provenance)
        print(f"DONE {lesson_id}: {timeline_duration:.3f}s including {args.outro:g}s outro; "
              f"decoded peak {decoded_check['peak']:.4f}; {audio_path.stat().st_size:,} bytes", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SourcePolicyError as exc:
        raise SystemExit(f"Source policy: {exc}")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit(f"Audio preparation: {exc}")
