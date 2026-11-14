"""Convert an owned audio file using ffmpeg to Spaceport's bounded PCM format."""
import argparse,subprocess
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('input',type=Path);ap.add_argument('cue',choices=['direct','internal','queue','group','priority','partner','info','urgent']);args=ap.parse_args()
out=Path(__file__).resolve().parents[1]/'data/sounds'/(args.cue+'.wav');out.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['ffmpeg','-y','-i',str(args.input),'-t','8','-ac','1','-ar','22050','-c:a','pcm_s16le','-fflags','+bitexact','-flags:a','+bitexact','-map_metadata','-1',str(out)],check=True)
print('Converted '+args.cue+'; upload the filesystem to apply')
