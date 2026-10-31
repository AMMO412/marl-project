from pathlib import Path
from PIL import Image

src = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\draft7\render")
out = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\draft7\sheets")
out.mkdir(exist_ok=True)
pages = sorted(src.glob("page-*.png"))
per = 4
W, H = 620, 876
for i in range(0, len(pages), per):
    chunk = pages[i:i + per]
    sheet = Image.new("RGB", (W * 2 + 30, H * 2 + 30), (235, 238, 235))
    for j, p in enumerate(chunk):
        im = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
        x = 10 + (j % 2) * (W + 10)
        y = 10 + (j // 2) * (H + 10)
        sheet.paste(im, (x, y))
    name = out / ("sheet_%02d.png" % (i // per + 1))
    sheet.save(name)
    print(name, [p.name for p in chunk])




