#!/usr/bin/env python3
"""Bind inspected original-book artwork to stable phrase targets.

Target coordinates are authored after inspecting the actual generated image.
This command hashes existing bytes; it never generates or modifies images.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image
from guidance import validate_plan
from source_policy import SourcePolicy

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='Reviewed batch draft; other batch paths default to its directory')
    parser.add_argument('--targets', type=Path,
                        help='Defaults to inspected-targets.json beside --input')
    parser.add_argument('--output', type=Path,
                        help='Defaults to visual-guidance.json beside --input')
    parser.add_argument('--lesson', action='append')
    args = parser.parse_args()
    args.targets = args.targets or args.input.parent / 'inspected-targets.json'
    args.output = args.output or args.input.parent / 'visual-guidance.json'
    policy = SourcePolicy(ROOT)
    policy.require_book('shahzad-raja-2015-200-practice-questions')
    document = read(args.input)
    lessons = document['lessons'] if isinstance(document, dict) else document
    policy.validate_authoring(document, lessons)
    targets = read(args.targets)
    plans = []
    for lesson in lessons:
        identity = lesson['id']
        if args.lesson and identity not in args.lesson:
            continue
        inspected = targets.get(identity)
        if inspected is None:
            raise ValueError(f'Missing inspected coordinates for {identity}')
        if not inspected.get('visuallyInspected'):
            raise ValueError(f'Artwork has not been visually inspected: {identity}')
        poster = lesson['poster']
        real = lesson['realImage']['url']
        images = {}
        for relative in dict.fromkeys([poster, real]):
            path = (ROOT / 'web' / relative).resolve()
            path.relative_to((ROOT / 'web').resolve())
            with Image.open(path) as im:
                im.load()
                width, height = im.size
            images[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                'width': width, 'height': height}
        target_records = {}
        for key, target in inspected['targets'].items():
            target_records[key] = dict(target)
            target_records[key].setdefault('image', poster)
            target_records[key].setdefault('zoom', 1.13)
        plan = {
            'id': identity,
            'audioLessonId': lesson['audioLessonId'],
            'images': images,
            'targets': target_records,
            'scenes': [{'id': scene['id'], 'phrases': scene['phrases']}
                       for scene in lesson['scenes']],
            'annotationNotes': inspected.get('notes', []) + [
                'Original generated mnemonic, explicitly distinguished from clinical imaging.',
                'Coordinates were authored on the final image bytes. Abstract or absent concepts have null targets.',
                'Clinical photographs retain their full framing. No anatomical point is inferred from the mnemonic.'
            ]
        }
        if inspected.get('outroTargetId'):
            plan['outroTargetId'] = inspected['outroTargetId']
        validate_plan(plan, lesson['scenes'], ROOT / 'web')
        plans.append(plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'schemaVersion': 1, 'lessons': plans}, indent=2) + '\n')
    print(json.dumps({'guidancePlans': len(plans), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
