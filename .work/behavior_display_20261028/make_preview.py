from pathlib import Path
from PIL import Image

root = Path('D:/Desktop/MARL项目')
paths = sorted((root / '.work/behavior_display_20261028/frames').glob('*.png'))
frames = [Image.open(path).convert('RGB') for path in paths]
assert len(frames) == 22 and len({frame.size for frame in frames}) == 1
out = root / 'planning_middle_demo/outputs/behavior_20261028_verify/hold_preview.gif'
frames[0].save(out, save_all=True, append_images=frames[1:],
               duration=[400] * 21 + [1400], loop=0, optimize=True)
with Image.open(out) as result:
    assert result.n_frames == 22
print(f'GIF verified: 22 frames, {out.stat().st_size} bytes')
