"""Monotonic focus orbit and deterministic falling-pixel progress; no PBX actions."""
import math


class FocusTimer:
    def __init__(self):
        self.minutes = 25
        self.phase = 'ready'
        self.started = 0
        self.duration = 25*60000
        self.paused_at = None
        self.completed = 0

    @property
    def active(self):
        return self.phase in ('focus','break')

    def tick(self, now):
        if not self.active or self.paused_at is not None:
            return
        if now-self.started >= self.duration:
            self.started += self.duration
            if self.phase == 'focus':
                self.completed += 1
                self.phase = 'break'
                self.duration = (15 if self.completed % 4 == 0 else 5)*60000
            else:
                self.phase = 'done'
            if self.phase == 'break' and now-self.started >= self.duration:
                self.phase = 'done'

    def toggle(self, now):
        self.tick(now)
        if not self.active:
            self.phase='focus';self.started=now;self.duration=self.minutes*60000;self.paused_at=None
        elif self.paused_at is None:
            self.paused_at=now
        else:
            self.started+=max(0,now-self.paused_at);self.paused_at=None

    def reset(self):
        self.phase='ready';self.paused_at=None

    def remaining(self, now):
        self.tick(now)
        if self.phase=='ready':return self.minutes*60
        if self.phase=='done':return 0
        elapsed=(self.paused_at if self.paused_at is not None else now)-self.started
        return max(0,(self.duration-max(0,elapsed)+999)//1000)

    def progress(self, now):
        self.tick(now)
        if self.phase=='ready':return 0
        if self.phase=='done':return 1
        elapsed=(self.paused_at if self.paused_at is not None else now)-self.started
        return min(1,max(0,elapsed/self.duration))

    def adjust(self, direction):
        if not self.active:
            self.minutes=max(5,min(90,self.minutes+5*direction))

    def led_frame(self, now, brightness):
        progress=self.progress(now);level=int(255*max(0,min(1,brightness)))
        frame=[]
        for i in range(12):
            fill=max(0,min(1,progress*12-i))
            glow=int(level*(.06+.65*fill))
            frame.append((int(glow*.15),glow if self.phase=='break' else int(glow*.75),int(glow*.55) if self.phase=='break' else glow))
        head=min(11,int(progress*12));frame[head]=(int(level*.2),int(level*.8),level)
        return frame


def quiet(payload, live):
    if not live or not isinstance(payload,dict):return False
    for member in [payload.get('own') or {}]+list(payload.get('team') or []):
        if not isinstance(member,dict) or member.get('calls') or member.get('state') in ('ringing','dialing','busy','connected','held','hold'):
            return False
    return True

def rain_frame(progress, now, peak, paused=False):
    """18x9 pixels. A sand bed fills with elapsed time; one comet falls above it."""
    width,height=18,9
    frame=bytearray(width*height)
    peak=max(0,min(255,int(peak)))
    filled=min(162,max(0,int(progress*162)))
    # A shuffled, complete permutation gives a natural, uneven bed without RNG,
    # allocation-heavy simulations, or changing already settled pixels.
    for i in range(filled):
        layer=i//width;x=((i%width)*7+layer*5)%width;y=height-1-layer
        frame[y*width+x]=max(1,peak*2//5) if peak else 0
    if not paused and filled<162:
        step=now//180
        floor=height-1-filled//width
        travel=max(1,floor+1);x=((step//travel)*7+3)%width
        head=step%travel
        for tail in range(4):
            y=head-tail
            if y>=0 and not frame[y*width+x]:frame[y*width+x]=peak//(tail+1)
    return frame


def draw(ctx, timer, now):
    progress=timer.progress(now)
    accent=(.18,.80,1) if timer.phase!='break' else (.30,.94,.62)
    ctx.rgb(.015,.025,.065).rectangle(-120,-120,240,240).fill()
    for i in range(22):
        x=((i*67)%220)-110;y=((i*43)%220)-110
        if x*x+y*y<115*115:
            ctx.rgb(.12,.18,.29).arc(x,y,.65,0,6.283,False).fill()
    ctx.line_width=4
    ctx.rgb(.045,.12,.19).arc(0,0,110,0,6.283,False).stroke()
    if progress:
        ctx.rgb(*accent).arc(0,0,110,-math.pi/2,-math.pi/2+progress*6.283,False).stroke()
    angle=-math.pi/2+progress*6.283
    x,y=110*math.cos(angle),110*math.sin(angle)
    ctx.rgb(*accent).arc(x,y,4,0,6.283,False).fill()
    ctx.text_align=ctx.CENTER;ctx.text_baseline=ctx.MIDDLE
    ctx.font_size=14;ctx.rgb(*accent).move_to(0,-68).text('FOCUS ORBIT')
    seconds=timer.remaining(now)
    ctx.font_size=53;ctx.rgb(.92,.97,1).move_to(0,-14).text('%02d:%02d'%(seconds//60,seconds%60))
    label='PAUSED' if timer.paused_at is not None else {'ready':'READY TO LAUNCH','focus':'IN FOCUS','break':'TAKE A BREAK','done':'ORBIT COMPLETE'}[timer.phase]
    ctx.font_size=14;ctx.rgb(*accent).move_to(0,31).text(label)
    ctx.font_size=10;ctx.rgb(.55,.68,.79).move_to(0,57).text('%d ORBITS COMPLETE'%timer.completed)
    ctx.font_size=10;ctx.move_to(0,79).text('C START / PAUSE   D RESET')
    ctx.font_size=9;ctx.move_to(0,95).text('F/B DURATION   A BACK')
