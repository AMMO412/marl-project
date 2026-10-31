"""Convert the packaged 16-bit elevation image into a GUI mesh (Windows Python)."""
from pathlib import Path
from PIL import Image

here = Path(__file__).resolve().parent
source = here.parent / 'GazeboUE-single-container-v1/assets/environment/models/yosemite/media/yosemite_elevation.png'
image = Image.open(source)
width, height = image.size
target = here / 'generated/yosemite_visual.obj'
target.parent.mkdir(exist_ok=True)
with target.open('w', encoding='ascii') as file:
    file.write('# Visual derivative of the packaged elevation image; physics stays heightmap.\n')
    for row in range(height):
        for col in range(width):
            x = 280 * col / (width - 1) - 140
            y = 140 - 280 * row / (height - 1)
            z = image.getpixel((col, row)) / 65535 * 90 - 10
            file.write(f'v {x:.6f} {y:.6f} {z:.6f}\n')
    for row in range(height - 1):
        for col in range(width - 1):
            a = row * width + col + 1
            b, c, d = a + 1, a + width, a + width + 1
            file.write(f'f {a} {c} {b}\nf {b} {c} {d}\n')
print(target)
