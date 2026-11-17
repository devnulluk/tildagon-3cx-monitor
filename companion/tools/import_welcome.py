"""Convert a local welcome clip into an ignored firmware asset (requires imageio-ffmpeg)."""
import argparse,subprocess
from pathlib import Path
import imageio_ffmpeg
ap=argparse.ArgumentParser();ap.add_argument('input',type=Path);args=ap.parse_args()
result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(args.input),'-t','8','-ac','1','-ar','22050','-f','s16le','-'],capture_output=True,check=True)
data=result.stdout
if not data or len(data)%2:raise SystemExit('Invalid PCM output')
out=Path(__file__).resolve().parents[1]/'include/welcome_audio.private.h'
out.write_text('#pragma once\nstatic const unsigned char WELCOME_PCM[] PROGMEM={\n'+','.join(str(x) for x in data)+'};\nstatic constexpr unsigned WELCOME_SAMPLES='+str(len(data)//2)+';\n')
print('Converted welcome: %.3f seconds'%(len(data)/44100))
