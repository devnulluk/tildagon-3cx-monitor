"""Original generated ringtone pack, PCM WAV, no copyrighted samples."""
import math,struct,wave
from pathlib import Path
TUNES={'direct':[523,659,784,659],'internal':[440,660,440,660],
       'queue':[587,740,880,740],'group':[440,554,659,554],
       'priority':[880,1109,1320,1109],'partner':[659,784,988,1175],
       'info':[784,1047,0,0],'urgent':[440,554,440,554]}
def build(root):
    root.mkdir(parents=True,exist_ok=True)
    for name,notes in TUNES.items():
        frames=bytearray()
        for i in range(int(22050*2.8)):
            t=i/22050;within=t%.18;f=notes[int(t/.18)%4]
            env=min(1,within/.012)*min(1,max(0,(.15-within)/.04))
            value=(math.sin(t*math.tau*f)+.18*math.sin(t*math.tau*f*2))*env if f and t<1.3 else 0
            frames.extend(struct.pack('<h',int(value*11000)))
        with wave.open(str(root/(name+'.wav')),'wb') as out:
            out.setparams((1,2,22050,0,'NONE','not compressed'));out.writeframes(frames)
if __name__=='__main__':build(Path(__file__).resolve().parents[1]/'data/sounds')
