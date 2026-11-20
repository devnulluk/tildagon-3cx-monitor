"""Render production code with synthetic time; these are previews, not photos."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw

parser=argparse.ArgumentParser()
parser.add_argument('--renderer',required=True,help='Compiled companion/tests/render_preview.cpp executable')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
out=root/'companion/docs';out.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('arecibo_preview',root/'badge/arecibo.py')
message=importlib.util.module_from_spec(spec);spec.loader.exec_module(message)
frames=[]
with tempfile.TemporaryDirectory() as folder:
    ppm=Path(folder)/'frame.ppm'
    for ms in range(0,24750,250):
        subprocess.run([str(Path(args.renderer).resolve()),'arecibo',str(ppm),str(ms)],check=True)
        frames.append(Image.open(ppm).convert('RGB').copy())
frames[50].save(out/'arecibo.png')
frames[0].save(out/'arecibo-scroll.gif',save_all=True,append_images=frames[1:],duration=250,loop=0,optimize=True)
matrix=[]
for ms in range(0,56700,500):
    im=Image.new('RGB',(320,205),'#07111f');draw=ImageDraw.Draw(im)
    draw.text((24,16),'ARECIBO / MATRIX LANDSCAPE',fill='#78e6ef')
    pixels=message.matrix_frame(ms,90)
    for y in range(9):
        for x in range(18):
            if y==0 and (x<3 or x>14):continue
            level=pixels[y*18+x]
            colour=(255,211,82) if level else (29,36,43)
            px,py=25+x*15,47+y*15
            draw.rounded_rectangle((px,py,px+10,py+10),radius=3,fill=colour)
    draw.text((25,187),'Production bitmap / host preview',fill='#7c91a8')
    matrix.append(im)
matrix[0].save(out/'arecibo-matrix.gif',save_all=True,append_images=matrix[1:],duration=500,loop=0,optimize=True)
print('Arecibo LCD and matrix animation previews saved')
