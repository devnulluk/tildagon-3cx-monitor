"""Host renders production ui.h with synthetic data; not physical screenshots.
Run after PlatformIO installed the pinned font dependency. Requires a C++17 compiler and Pillow.
"""
import argparse,shutil,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageDraw
ap=argparse.ArgumentParser();ap.add_argument('--compiler',default='g++');ap.add_argument('--video',action='store_true');args=ap.parse_args()
root=Path(__file__).resolve().parents[1];out=root/'docs';out.mkdir(exist_ok=True)
scenes=['weather','rain','moon','meteors','notification','urgent','advent','offline']
with tempfile.TemporaryDirectory() as temp:
 t=Path(temp);fonts=t/'Fonts';fonts.mkdir()
 for name in ['FreeSansBold24pt7b.h','FreeSansBold12pt7b.h','FreeSans9pt7b.h']:
  src=root/'.pio/libdeps/spaceport/Adafruit GFX Library/Fonts'/name
  (fonts/name).write_text('\n'.join(line for line in src.read_text(encoding='utf-8').splitlines() if '#include' not in line))
 exe=t/'render.exe'
 subprocess.run([args.compiler,'-std=c++17','-I'+str(root/'tests/host'),'-I'+str(root/'include'),'-I'+str(t),str(root/'tests/render_preview.cpp'),'-o',str(exe)],check=True)
 frames=[];sheet=Image.new('RGB',(1200,840),'#060b18');draw=ImageDraw.Draw(sheet)
 for i,scene in enumerate(scenes):
  ppm=t/'frame.ppm';subprocess.run([str(exe),scene,str(ppm),'1800'],check=True)
  im=Image.open(ppm).convert('RGB');im.save(out/(scene+'.png'))
  if i<8:
   x=(i%4)*300;y=(i//4)*420;sheet.paste(im.resize((288,288)),(x+6,y+30));draw.text((x+16,y+330),scene.upper(),fill='#69e7ff')
  for f in range(12):
   subprocess.run([str(exe),scene,str(ppm),str(f*180)],check=True)
   frames.append(Image.open(ppm).convert('RGB').copy())
 sheet.save(out/'spaceport-gallery.png')
 frames[0].save(out/'spaceport-tour.gif',save_all=True,append_images=frames[1:],duration=180,loop=0,optimize=True)
print('Host previews saved:',out)

if args.video:
 import array,wave,imageio_ffmpeg
 audio=out/'preview-audio.wav'
 cues=['','','','','info','urgent','','']
 with wave.open(str(audio),'wb') as w:
  w.setparams((1,2,22050,0,'NONE','not compressed'))
  for cue in cues:
   count=47628
   if cue:
    with wave.open(str(root/'data/sounds'/(cue+'.wav')),'rb') as sample:data=array.array('h',sample.readframes(count))
    data=array.array('h',(int(v*.2) for v in data));w.writeframes(data.tobytes())
   else:w.writeframes(bytes(count*2))
 writer=imageio_ffmpeg.write_frames(str(out/'spaceport-tour.mp4'),(360,360),fps=1000/180,macro_block_size=2,quality=8,audio_path=str(audio),audio_codec='aac')
 writer.send(None)
 for frame in frames:writer.send(frame.tobytes())
 writer.close();audio.unlink()
