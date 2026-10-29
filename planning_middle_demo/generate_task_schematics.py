# -*- coding: utf-8 -*-
"""生成五类任务的固定时间轴示意动画，不调用规划器或执行器。

py -3.14 planning_middle_demo/generate_task_schematics.py --references <图片目录>
输出的 index.html 内嵌图片、样式和脚本，可独立离线打开。
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def generate(references, output):
    destination = Path(output)
    if destination.exists() and any(destination.iterdir()):
        previous = destination / 'manifest.json'
        if (not previous.is_file() or
                json.loads(previous.read_text(encoding='utf-8-sig')).get('kind')
                != 'fixed_timeline_schematic'):
            raise ValueError('输出目录不是本示意页目录，拒绝覆盖既有产物：%s' % destination)
    refs = Path(references)
    images = []
    evidence = []
    for number in range(1, 7):
        source = refs / ('image-%d.png' % number)
        raw = source.read_bytes()
        images.append('data:image/png;base64,' + base64.b64encode(raw).decode('ascii'))
        evidence.append(dict(number=number, file=str(source.resolve()),
                             sha256=hashlib.sha256(raw).hexdigest()))
    template = (ROOT / 'task_motion_schematics.html').read_text(encoding='utf-8')
    page = template.replace('__REFERENCE_IMAGES__', json.dumps(images))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'index.html').write_text(page, encoding='utf-8')
    manifest = dict(kind='fixed_timeline_schematic',
                    backend='svg_keyframe_animation',
                    execution_or_simulation_result=False,
                    reference_images=evidence,
                    source_template=str((ROOT / 'task_motion_schematics.html').resolve()),
                    duration_animation_seconds=36,
                    modes=['patrol', 'boundary', 'stages', 'exploration', 'handover'])
    (destination / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return destination / 'index.html'


def main():
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'outputs/task_motion_schematics_20261027')
    args = parser.parse_args()
    print('动态示意页：%s' % generate(args.references, args.out).resolve())


if __name__ == '__main__':
    main()
