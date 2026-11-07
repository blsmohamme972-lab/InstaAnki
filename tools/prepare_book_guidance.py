#!/usr/bin/env python3
"""Bind inspected original-book artwork to stable phrase targets.

Target coordinates are authored after inspecting the actual generated image.
This command hashes existing bytes; it never generates or modifies images.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile

from PIL import Image
from guidance import asset_file, canonical_hash, validate_plan
from source_policy import SourcePolicy

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def select_lessons(document, requested):
    if not isinstance(document, dict) or not isinstance(document.get('lessons'), list) or not document['lessons']:
        raise ValueError('A source-bound draft with a nonempty lessons array is required')
    lessons = document['lessons']
    identities = [lesson.get('id') for lesson in lessons if isinstance(lesson, dict)]
    if (len(identities) != len(lessons) or any(not isinstance(value, str) or not value.strip() for value in identities)
            or len(set(identities)) != len(identities)):
        raise ValueError('Draft lesson identities must be unique nonempty strings')
    if requested:
        if len(set(requested)) != len(requested) or set(requested) - set(identities):
            raise ValueError('--lesson must name existing draft lessons exactly once; no guidance was written')
        lessons = [lesson for lesson in lessons if lesson['id'] in requested]
    return lessons


def reviewed_images(lesson, inspected, web_root):
    """Validate recorded inspection bytes, never approve new bytes implicitly."""
    if (not isinstance(inspected, dict) or type(inspected.get('schemaVersion')) is not int
            or inspected['schemaVersion'] != 1 or inspected.get('visuallyInspected') is not True):
        raise ValueError(f"{lesson['id']}: record an actual schemaVersion-1 visual inspection with visuallyInspected:true")
    reviewer = inspected.get('reviewer')
    notes = inspected.get('notes')
    if (not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(notes, list) or not notes
            or any(not isinstance(note, str) or not note.strip() for note in notes)):
        raise ValueError('Visual inspection requires its actual reviewer and nonempty inspection notes')
    try:
        reviewed_at = datetime.fromisoformat(inspected.get('reviewedAt', '').replace('Z', '+00:00'))
        if reviewed_at.utcoffset() is None or reviewed_at > datetime.now(timezone.utc):
            raise ValueError('Inspection time is missing its timezone or is in the future')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Visual inspection requires an actual timezone-aware reviewedAt, not a future review') from None
    target_records = inspected.get('targets')
    if not isinstance(target_records, dict) or not target_records or any(not isinstance(value, dict) for value in target_records.values()):
        raise ValueError('Visual inspection requires named inspected targets')
    poster, real = lesson['poster'], lesson['realImage']['url']
    paths = [poster, real, *(scene.get('image', poster) for scene in lesson['scenes']),
             *(target.get('image', poster) for target in target_records.values())]
    if any(not isinstance(path, str) or not path.startswith('media/') for path in paths):
        raise ValueError('Inspected images must use canonical local media paths')
    expected = inspected.get('images')
    if not isinstance(expected, dict) or set(expected) != set(paths):
        raise ValueError('Inspection images must bind every poster, clinical, scene and target image with sha256/width/height')
    images = {}
    for relative in dict.fromkeys(paths):
        path = asset_file(web_root, relative)
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as decoded:
            decoded.load()
            width, height = decoded.size
        current = {'sha256': hashlib.sha256(raw).hexdigest(), 'width': width, 'height': height}
        record = expected[relative]
        if (not isinstance(record, dict) or type(record.get('width')) is not int
                or type(record.get('height')) is not int
                or any(record.get(key) != value for key, value in current.items())):
            raise ValueError(f'Image bytes or dimensions differ from their actual target inspection; review again: {relative}')
        images[relative] = current
    return images


def check_output(output, inputs, selected_ids):
    if output.resolve() in {path.resolve() for path in inputs}:
        raise ValueError('Guidance output must not overwrite its draft or inspection input')
    if output.exists():
        previous = read(output)
        if (not isinstance(previous, dict) or previous.get('schemaVersion') != 1
                or not isinstance(previous.get('lessons'), list)
                or any(not isinstance(plan, dict) or not isinstance(plan.get('images'), dict)
                       or not isinstance(plan.get('targets'), dict) for plan in previous['lessons'])):
            raise ValueError('Output already exists and is not a guidance document; choose another path')
        if {plan.get('id') for plan in previous['lessons']} - set(selected_ids):
            raise ValueError('This selection would drop other guidance plans; use a separate --output or prepare the complete batch')


def write_output(path, document):
    data = json.dumps(document, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.visual-guidance-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='Reviewed batch draft; other batch paths default to its directory')
    parser.add_argument('--targets', type=Path,
                        help='Defaults to inspected-targets.json beside --input')
    parser.add_argument('--output', type=Path,
                        help='Defaults to visual-guidance.json beside --input')
    parser.add_argument('--lesson', action='append', help='Select existing lesson IDs; use a separate output for a subset')
    args = parser.parse_args()
    args.targets = args.targets or args.input.parent / 'inspected-targets.json'
    args.output = args.output or args.input.parent / 'visual-guidance.json'
    policy = SourcePolicy(ROOT)
    policy.require_book('shahzad-raja-2015-200-practice-questions')
    document = read(args.input)
    lessons = select_lessons(document, args.lesson)
    check_output(args.output, (args.input, args.targets), [lesson['id'] for lesson in lessons])
    policy.validate_authoring(document, lessons)
    targets = read(args.targets)
    if not isinstance(targets, dict):
        raise ValueError('Target inspection records must be keyed by lesson ID')
    plans = []
    for lesson in lessons:
        identity = lesson['id']
        inspected = targets.get(identity)
        if inspected is None:
            raise ValueError(f'Missing inspected coordinates for {identity}')
        poster = lesson['poster']
        real = lesson['realImage']['url']
        images = reviewed_images(lesson, inspected, ROOT / 'web')
        clinical = {real, *(image['url'] for image in lesson.get('realImages', []))}
        target_records = {}
        for key, target in inspected['targets'].items():
            target_records[key] = dict(target)
            target_records[key].setdefault('image', poster)
            target_records[key].setdefault('zoom', 1 if target_records[key]['image'] in clinical else 1.13)
            if target_records[key]['image'] in clinical and target_records[key]['zoom'] != 1:
                raise ValueError('Clinical targets must retain uncropped framing with zoom 1')
        plan = {
            'id': identity,
            'audioLessonId': lesson['audioLessonId'],
            'images': images,
            'targets': target_records,
            'scenes': [{'id': scene['id'], 'phrases': scene['phrases']}
                       for scene in lesson['scenes']],
            'inspection': {'reviewer': inspected['reviewer'], 'reviewedAt': inspected['reviewedAt'],
                           'recordSha256': canonical_hash(inspected)},
            'annotationNotes': inspected.get('notes', []) + [
                'Original generated mnemonic, explicitly distinguished from clinical imaging.',
                'Coordinates were authored on the final image bytes. Abstract or absent concepts have null targets.',
                'Clinical photographs retain their full framing. No anatomical point is inferred from the mnemonic.'
            ]
        }
        if inspected.get('outroTargetId'):
            plan['outroTargetId'] = inspected['outroTargetId']
        validate_plan(plan, lesson['scenes'], ROOT / 'web')
        for scene in lesson['scenes']:
            for phrase in scene['phrases']:
                target_id = phrase.get('targetId')
                if target_id is not None and target_records[target_id]['image'] != scene.get('image', poster):
                    raise ValueError('A phrase target must be on the image displayed in its scene')
        if plan.get('outroTargetId') and target_records[plan['outroTargetId']]['image'] != real:
            raise ValueError('The outro target must refer to the primary clinical image')
        plans.append(plan)
    write_output(args.output, {'schemaVersion': 1, 'lessons': plans})
    print(json.dumps({'guidancePlans': len(plans), 'output': str(args.output)}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise SystemExit(f'Visual-guidance checkpoint: {error}')
