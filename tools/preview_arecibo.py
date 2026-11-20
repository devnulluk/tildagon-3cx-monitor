"""Render production code with synthetic time; these are previews, not photos."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from PIL import Image

parser=argparse.ArgumentParser()
parser.add_argument('--renderer',required=True,help='Compiled companion/tests/render_preview.cpp executable')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
out=root/'companion/docs';out.mkdir(exist_ok=True)
frames=[]
with tempfile.TemporaryDirectory() as folder:
    ppm=Path(folder)/'frame.ppm'
    for ms in range(0,24750,250):
        subprocess.run([str(Path(args.renderer).resolve()),'arecibo',str(ppm),str(ms)],check=True)
        frames.append(Image.open(ppm).convert('RGB').copy())
frames[50].save(out/'arecibo.png')
frames[0].save(out/'arecibo-scroll.gif',save_all=True,append_images=frames[1:],duration=250,loop=0,optimize=True)
print('Arecibo LCD animation preview saved')
