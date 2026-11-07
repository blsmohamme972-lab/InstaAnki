#!/usr/bin/env python3
"""Validate an InstaAnki content pack (a directory or a .zip file).

Usage:
    python3 tools/validate_pack.py <pack-dir-or-zip> [--schema-dir DIR] [--strict]

Exit code 0 = valid (warnings allowed unless --strict), 1 = invalid.

Checks:
  * pack.json / reel.json / transcript.json against the JSON Schemas in ./schema
    (needs `pip install jsonschema`; skipped with a warning if it is missing)
  * every file reference exists, zip entries are safe (no path traversal)
  * SVG images are safe (no <script>, no event handlers, no external links)
    and contain no baked-in <text> labels
  * cross references: regions -> images / SVG ids, cues -> regions / images,
    questions -> segments, pretest, recap, cloze timings, compare targets
  * timing: everything inside the audio duration, segments ordered and
    non-overlapping, transcript words ordered
  * audio duration matches reel.duration (needs ffprobe; skipped if missing)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_DIR = ROOT / "schema"

AUDIO_EXT = {".opus", ".ogg", ".m4a", ".mp3", ".wav"}
IMAGE_EXT = {".svg", ".webp", ".png", ".jpg", ".jpeg"}
REGION_CUES = {"spotlight", "label", "arrow", "pulse", "camera"}
MAX_IMAGE_BYTES = 1_500_000
MAX_AUDIO_BYTES = 3_000_000
RECOMMENDED_DURATION = (55.0, 100.0)
AUDIO_TOLERANCE = 0.5


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"[{where}] {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"[{where}] {msg}")

    def info(self, where: str, msg: str) -> None:
        self.infos.append(f"[{where}] {msg}")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def load_json(path: Path, rep: Report, where: str):
    if not path.is_file():
        rep.err(where, f"missing file: {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        rep.err(where, f"invalid JSON in {path.name}: {exc}")
        return None


class SchemaChecker:
    def __init__(self, schema_dir: Path, rep: Report) -> None:
        self.validators = {}
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            rep.warn("setup", "jsonschema not installed -> schema checks skipped "
                              "(pip install jsonschema)")
            return
        from jsonschema import Draft202012Validator
        for name in ("pack", "reel", "transcript"):
            path = schema_dir / f"{name}.schema.json"
            if not path.is_file():
                rep.warn("setup", f"schema not found: {path} -> {name} schema checks skipped")
                continue
            self.validators[name] = Draft202012Validator(
                json.loads(path.read_text(encoding="utf-8")))

    def check(self, name: str, obj, rep: Report, where: str) -> bool:
        validator = self.validators.get(name)
        if validator is None:
            return True
        ok = True
        for e in sorted(validator.iter_errors(obj), key=lambda e: list(map(str, e.absolute_path))):
            loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
            rep.err(where, f"schema: {loc}: {e.message}")
            ok = False
        return ok


def safe_rel(base: Path, rel: str, rep: Report, where: str) -> Path | None:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        rep.err(where, f"unsafe path: {rel}")
        return None
    return base.joinpath(*p.parts)


def ffprobe_duration(path: Path) -> float | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30, check=True)
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


SVG_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")
SVG_DANGER = [
    (re.compile(r"<\s*script\b", re.I), "contains <script>"),
    (re.compile(r"<\s*foreignObject\b", re.I), "contains <foreignObject>"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "contains an event handler attribute (on...=)"),
    (re.compile(r"""(?:xlink:)?href\s*=\s*["']\s*(?:https?:|javascript:|data:text/html)""", re.I),
     "references an external/script URL"),
]
SVG_TEXT_RE = re.compile(r"<\s*text\b", re.I)


def check_svg(path: Path, rep: Report, where: str) -> set[str]:
    try:
        src = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        rep.err(where, f"{path.name}: SVG is not UTF-8 text")
        return set()
    for rx, msg in SVG_DANGER:
        if rx.search(src):
            rep.err(where, f"{path.name}: unsafe SVG, {msg}")
    if SVG_TEXT_RE.search(src):
        rep.warn(where, f"{path.name}: SVG contains <text>; labels must be overlays "
                        "(regions.label), not baked into images")
    return set(SVG_ID_RE.findall(src))


# --------------------------------------------------------------------------- #
# reel validation
# --------------------------------------------------------------------------- #

def validate_reel(reel_dir: Path, reel_id: str, pack_reels: dict, schemas: SchemaChecker,
                  rep: Report) -> None:
    where = f"reel {reel_id}"
    reel = pack_reels.get(reel_id)
    if reel is None:
        return
    if not schemas.check("reel", reel, rep, where):
        rep.info(where, "cross-reference checks run on a best-effort basis after schema errors")

    if reel.get("id") != reel_id:
        rep.err(where, f"reel.json id '{reel.get('id')}' must equal its folder name '{reel_id}'")

    duration = reel.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        rep.err(where, "duration missing or invalid; remaining timing checks skipped")
        duration = None
    elif not (RECOMMENDED_DURATION[0] <= duration <= RECOMMENDED_DURATION[1]):
        rep.warn(where, f"duration {duration:.1f}s is outside the recommended 60-90 s range")

    def in_time(t, what: str, allow_end: bool = True) -> None:
        if duration is None or not isinstance(t, (int, float)):
            return
        limit = duration + (0.01 if allow_end else 0)
        if t < 0 or t > limit:
            rep.err(where, f"{what}: time {t} is outside 0..{duration}")

    # ---- audio ------------------------------------------------------------
    audio_rel = reel.get("audio")
    if isinstance(audio_rel, str):
        audio = safe_rel(reel_dir, audio_rel, rep, where)
        if audio is not None:
            if not audio.is_file():
                rep.err(where, f"audio file not found: {audio_rel}")
            else:
                if audio.suffix.lower() not in AUDIO_EXT:
                    rep.err(where, f"audio format {audio.suffix} not allowed ({sorted(AUDIO_EXT)})")
                if audio.suffix.lower() == ".wav":
                    rep.warn(where, "WAV audio is large; prefer Opus (.opus) ~48 kbps mono")
                if audio.stat().st_size > MAX_AUDIO_BYTES:
                    rep.warn(where, f"audio is {audio.stat().st_size // 1024} KB; "
                                    "aim for < 1 MB (Opus 48 kbps mono)")
                real = ffprobe_duration(audio)
                if real is None:
                    rep.info(where, "ffprobe unavailable -> audio duration not verified")
                elif duration is not None and abs(real - duration) > AUDIO_TOLERANCE:
                    rep.err(where, f"reel.duration {duration}s != audio length {real:.2f}s")

    # ---- transcript -------------------------------------------------------
    words = []
    tr_rel = reel.get("transcript")
    if isinstance(tr_rel, str):
        tr_path = safe_rel(reel_dir, tr_rel, rep, where)
        if tr_path is not None:
            transcript = load_json(tr_path, rep, where)
            if transcript is not None and schemas.check("transcript", transcript, rep,
                                                        f"{where} transcript"):
                words = transcript.get("words", [])
                prev = -1.0
                for i, w in enumerate(words):
                    s, e = w.get("s"), w.get("e")
                    if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
                        continue
                    if s >= e:
                        rep.err(where, f"transcript word #{i} '{w.get('w')}': s >= e")
                    if s < prev - 1e-6:
                        rep.err(where, f"transcript word #{i} '{w.get('w')}' is out of order")
                    prev = s
                    if duration is not None and e > duration + AUDIO_TOLERANCE:
                        rep.err(where, f"transcript word #{i} ends after the audio ({e}s)")
                if duration is not None and words and isinstance(words[-1].get("e"), (int, float)):
                    if duration - words[-1]["e"] > 5:
                        rep.warn(where, "more than 5 s of silence after the last word")
                if not any(w.get("key") for w in words):
                    rep.warn(where, "no transcript word is marked key=true "
                                    "(used to highlight key terms in captions)")

    # ---- images -----------------------------------------------------------
    images = reel.get("images") or {}
    svg_ids: dict[str, set[str]] = {}
    for key, img in images.items():
        if not isinstance(img, dict) or not isinstance(img.get("src"), str):
            continue
        path = safe_rel(reel_dir, img["src"], rep, where)
        if path is None:
            continue
        if not path.is_file():
            rep.err(where, f"image '{key}': file not found: {img['src']}")
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXT:
            rep.err(where, f"image '{key}': format {ext} not allowed ({sorted(IMAGE_EXT)})")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            rep.warn(where, f"image '{key}' is {path.stat().st_size // 1024} KB (limit 1.5 MB)")
        if ext == ".svg":
            svg_ids[key] = check_svg(path, rep, where)
        elif ext in {".png", ".jpg", ".jpeg"}:
            rep.info(where, f"image '{key}': prefer SVG for diagrams or WebP for photos")
        if max(img.get("width", 0), img.get("height", 0)) > 4096:
            rep.warn(where, f"image '{key}': dimensions above 4096 px")

    # ---- regions ----------------------------------------------------------
    regions = reel.get("regions") or {}
    if "full" in regions:
        rep.err(where, "region key 'full' is reserved for camera.target")
    for key, reg in regions.items():
        if not isinstance(reg, dict):
            continue
        img_key = reg.get("image")
        if img_key not in images:
            rep.err(where, f"region '{key}': unknown image '{img_key}'")
            continue
        if "svgId" in reg:
            if img_key not in svg_ids:
                rep.err(where, f"region '{key}': svgId used but image '{img_key}' is not an SVG")
            elif reg["svgId"] not in svg_ids[img_key]:
                rep.err(where, f"region '{key}': id '{reg['svgId']}' not found in "
                               f"{images[img_key].get('src')}")
        rect = reg.get("rect")
        if isinstance(rect, dict):
            if rect.get("x", 0) + rect.get("w", 0) > 1.0001 or rect.get("y", 0) + rect.get("h", 0) > 1.0001:
                rep.err(where, f"region '{key}': rect goes outside the image (x+w or y+h > 1)")
    quiz_regions = [k for k, r in regions.items() if isinstance(r, dict) and r.get("quiz", True)]
    if len(quiz_regions) < 2:
        rep.warn(where, "fewer than 2 quiz regions: auto formats identify/locate "
                        "need at least 2 (ideally 3+) labelled regions")

    # ---- segments ---------------------------------------------------------
    segments = [s for s in reel.get("segments") or [] if isinstance(s, dict)]
    seg_ids: set[str] = set()
    last_end = -1.0
    for s in segments:
        sid = s.get("id")
        if sid in seg_ids:
            rep.err(where, f"duplicate segment id '{sid}'")
        seg_ids.add(sid)
        st, en = s.get("start"), s.get("end")
        if not isinstance(st, (int, float)) or not isinstance(en, (int, float)):
            continue
        if st >= en:
            rep.err(where, f"segment '{sid}': start >= end")
        if st < last_end - 0.01:
            rep.err(where, f"segment '{sid}' overlaps the previous one or is out of order")
        last_end = en
        in_time(st, f"segment '{sid}'.start")
        in_time(en, f"segment '{sid}'.end")
    if segments and not any(s.get("importance") == "key" for s in segments):
        rep.err(where, "no segment has importance 'key'")

    # ---- cues -------------------------------------------------------------
    cues = [c for c in reel.get("cues") or [] if isinstance(c, dict)]
    shows = sorted((c for c in cues if c.get("type") == "show"
                    and isinstance(c.get("t"), (int, float))), key=lambda c: c["t"])
    if not shows or shows[0]["t"] > 0.05:
        rep.err(where, "the first cue must be a 'show' at t=0 (otherwise the screen is empty)")

    def image_at(t: float):
        cur = None
        for c in shows:
            if c["t"] <= t + 1e-6:
                cur = c.get("image")
        return cur

    def check_region_ref(rk, cue_desc: str, t: float, allow_full: bool = False) -> None:
        if rk is None or (allow_full and rk == "full"):
            return  # a missing reference is already reported by the schema check
        if rk not in regions:
            rep.err(where, f"{cue_desc}: unknown region '{rk}'")
            return
        shown = image_at(t)
        if shown is not None and regions[rk].get("image") != shown:
            rep.warn(where, f"{cue_desc}: region '{rk}' belongs to image "
                            f"'{regions[rk].get('image')}' but '{shown}' is on screen")

    prev_t = -1.0
    for i, c in enumerate(cues):
        t = c.get("t")
        ctype = c.get("type")
        desc = f"cue #{i} ({ctype} @ {t})"
        if not isinstance(t, (int, float)):
            continue
        if t < prev_t - 1e-6:
            rep.warn(where, f"{desc}: cues are not sorted by time")
        prev_t = t
        in_time(t, desc)
        until = c.get("until")
        if isinstance(until, (int, float)):
            if until <= t:
                rep.err(where, f"{desc}: until <= t")
            in_time(until, f"{desc}.until")
        if ctype == "show" and c.get("image") not in images:
            rep.err(where, f"{desc}: unknown image '{c.get('image')}'")
        elif ctype == "camera":
            check_region_ref(c.get("target"), desc, t, allow_full=True)
        elif ctype == "spotlight":
            targets = c.get("target")
            for rk in targets if isinstance(targets, list) else [targets]:
                check_region_ref(rk, desc, t)
        elif ctype in ("label", "pulse"):
            check_region_ref(c.get("region"), desc, t)
        elif ctype == "arrow":
            check_region_ref(c.get("from"), desc, t)
            check_region_ref(c.get("to"), desc, t)

    # ---- questions --------------------------------------------------------
    questions = [q for q in reel.get("questions") or [] if isinstance(q, dict)]
    q_by_id: dict[str, dict] = {}
    for q in questions:
        qid = q.get("id")
        qdesc = f"question '{qid}' ({q.get('type')})"
        if qid in q_by_id:
            rep.err(where, f"duplicate question id '{qid}'")
        q_by_id[qid] = q
        explain = q.get("explain")
        for sid in explain if isinstance(explain, list) else [explain]:
            if sid not in seg_ids:
                rep.err(where, f"{qdesc}: explain refers to unknown segment '{sid}'")
        opts = q.get("options")
        ans = q.get("answer")
        if isinstance(opts, list) and isinstance(ans, int) and not isinstance(ans, bool):
            if not 0 <= ans < len(opts):
                rep.err(where, f"{qdesc}: answer index {ans} out of range (0..{len(opts) - 1})")
        qtype = q.get("type")
        if qtype == "cloze":
            f, cut, res = q.get("from"), q.get("cut"), q.get("resume")
            if all(isinstance(x, (int, float)) for x in (f, cut, res)):
                if not f <= cut < res:
                    rep.err(where, f"{qdesc}: need from <= cut < resume")
                for name, x in (("from", f), ("cut", cut), ("resume", res)):
                    in_time(x, f"{qdesc}.{name}")
                if words and not any(abs(w.get("s", -99) - cut) <= 0.15 for w in words):
                    rep.warn(where, f"{qdesc}: 'cut' ({cut}) does not match the start of any "
                                    "transcript word (+-0.15 s)")
        elif qtype == "compare":
            if q.get("image") not in images:
                rep.err(where, f"{qdesc}: unknown image '{q.get('image')}'")
            other = q.get("otherReel")
            if other == reel_id:
                rep.err(where, f"{qdesc}: otherReel must be a different reel")
            elif other in pack_reels:
                other_imgs = (pack_reels[other] or {}).get("images") or {}
                if q.get("otherImage") not in other_imgs:
                    rep.err(where, f"{qdesc}: image '{q.get('otherImage')}' not found in reel '{other}'")
            else:
                rep.info(where, f"{qdesc}: reel '{other}' is not in this pack; "
                                "it must already exist in the app library")
        elif qtype == "teachback":
            kws = q.get("keywords") or []
            if isinstance(q.get("minHits"), int) and q["minHits"] > len(kws):
                rep.err(where, f"{qdesc}: minHits > number of keyword groups")

    pre = reel.get("pretest")
    if pre is not None:
        if pre not in q_by_id:
            rep.err(where, f"pretest refers to unknown question '{pre}'")
        elif q_by_id[pre].get("type") not in ("mcq", "truefalse"):
            rep.err(where, "pretest must be an mcq or truefalse question")
    post_video = [q for q in questions if q.get("type") == "mcq" and q.get("id") != pre]
    if not post_video:
        rep.err(where, "need at least one mcq that is not the pretest (asked after the video)")
    if sum(1 for q in questions if q.get("type") == "truefalse") < 2:
        rep.warn(where, "recommended: at least 2 truefalse statements")
    if len(questions) + len(quiz_regions) < 6:
        rep.warn(where, "few probes in total (questions + quiz regions < 6); "
                        "reviews will repeat the same probes often")

    recap = reel.get("recap")
    if isinstance(recap, dict):
        for sid in recap.get("segments") or []:
            if sid not in seg_ids:
                rep.err(where, f"recap refers to unknown segment '{sid}'")

    for rel in reel.get("related") or []:
        if isinstance(rel, dict) and rel.get("reel") not in pack_reels:
            rep.info(where, f"related reel '{rel.get('reel')}' is not in this pack")


# --------------------------------------------------------------------------- #
# pack validation
# --------------------------------------------------------------------------- #

def validate_pack_dir(pack_dir: Path, schemas: SchemaChecker, rep: Report) -> None:
    pack = load_json(pack_dir / "pack.json", rep, "pack")
    if pack is None:
        return
    schemas.check("pack", pack, rep, "pack")
    reel_ids = [r for r in pack.get("reels") or [] if isinstance(r, str)]
    reels_root = pack_dir / "reels"
    if not reels_root.is_dir():
        rep.err("pack", "missing folder: reels/")
        return

    on_disk = {p.name for p in reels_root.iterdir() if p.is_dir()}
    for extra in sorted(on_disk - set(reel_ids)):
        rep.warn("pack", f"folder reels/{extra} is not listed in pack.json reels")

    loaded: dict[str, dict | None] = {}
    for rid in reel_ids:
        rdir = reels_root / rid
        if not rdir.is_dir():
            rep.err("pack", f"listed reel '{rid}' has no folder reels/{rid}")
            continue
        loaded[rid] = load_json(rdir / "reel.json", rep, f"reel {rid}")

    for rid, data in loaded.items():
        if isinstance(data, dict):
            validate_reel(reels_root / rid, rid, loaded, schemas, rep)

    total = sum(f.stat().st_size for f in pack_dir.rglob("*") if f.is_file())
    if total > 50 * 1024 * 1024:
        rep.warn("pack", f"pack is {total // (1024 * 1024)} MB; split packs above 50 MB")
    rep.info("pack", f"{len(reel_ids)} reel(s), {total / 1024:.0f} KB total")


def extract_zip(zip_path: Path, dest: Path, rep: Report) -> Path | None:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        rep.err("zip", f"not a valid zip: {exc}")
        return None
    with zf:
        for name in zf.namelist():
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                rep.err("zip", f"unsafe entry path: {name}")
                return None
        zf.extractall(dest)
    if (dest / "pack.json").is_file():
        return dest
    subdirs = [p for p in dest.iterdir() if p.is_dir() and not p.name.startswith("__MACOSX")]
    if len(subdirs) == 1 and (subdirs[0] / "pack.json").is_file():
        rep.info("zip", f"pack found inside top-level folder '{subdirs[0].name}/'")
        return subdirs[0]
    rep.err("zip", "pack.json not found at the zip root (or inside a single top-level folder)")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate an InstaAnki content pack.")
    ap.add_argument("pack", type=Path, help="pack directory or .zip file")
    ap.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR,
                    help="folder containing pack/reel/transcript .schema.json")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()

    rep = Report()
    schemas = SchemaChecker(args.schema_dir, rep)
    tmp = None
    try:
        target = args.pack
        if target.is_file() and target.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="instaanki-pack-"))
            target = extract_zip(args.pack, tmp, rep)
        elif not target.is_dir():
            rep.err("input", f"not a directory or .zip: {args.pack}")
            target = None
        if target is not None:
            validate_pack_dir(target, schemas, rep)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)

    for line in rep.errors:
        print(f"ERROR   {line}")
    for line in rep.warnings:
        print(f"WARNING {line}")
    for line in rep.infos:
        print(f"INFO    {line}")
    failed = bool(rep.errors) or (args.strict and bool(rep.warnings))
    print(f"\n{'INVALID' if failed else 'VALID'}: "
          f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
