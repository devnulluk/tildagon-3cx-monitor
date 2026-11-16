import math
"""Read-only companion presence: stale or unknown status locks the screen."""
class AwayState:
    def __init__(self, configured=False):
        self.configured=bool(configured);self.received=None;self.value=None;self.welcome_until=0
    def accept(self,value,now):
        if not isinstance(value,dict) or value.get("version")!=1:return False
        if any(type(value.get(k)) is not bool for k in ("enabled","enrolled","nearby")):return False
        returning=(self.value is not None and self.value["enabled"] and self.value["enrolled"] and not self.value["nearby"] and value["enabled"] and value["enrolled"] and value["nearby"])
        if returning:self.welcome_until=now+2300
        if not value["nearby"]:self.welcome_until=0
        self.value={k:value[k] for k in ("enabled","enrolled","nearby")};self.received=now;return True
    def away(self,now):
        if not self.configured:return False
        if self.received is None or now-self.received>15000:return True
        return self.value["enabled"] and not (self.value["enrolled"] and self.value["nearby"])
    def welcoming(self,now):
        return not self.away(now) and now<self.welcome_until
    def label(self,now):
        if self.received is None or now-self.received>15000:return "PRESENCE OFFLINE"
        return "PHONE AWAY" if self.value["enrolled"] else "PAIR YOUR PHONE"

def draw_lock(ctx,label):
    ctx.rgb(.003,.006,.012).rectangle(-120,-120,240,240).fill()
    ctx.line_width=3
    ctx.rgb(.30,.45,.55).arc(0,-24,16,3.14159265,6.28318531,False).stroke()
    ctx.rgb(.16,.25,.32).round_rectangle(-24,-24,48,37,7).fill()
    ctx.rgb(.48,.66,.76).arc(0,-8,3,0,6.28318531,False).fill()
    ctx.font_size=16;ctx.rgb(.48,.66,.76).move_to(0,43).text("AWAY")
    ctx.font_size=10;ctx.rgb(.30,.45,.55).move_to(0,64).text(label)

def rainbow(now_ms, count=12, brightness=.05, ceiling=1.0):
    if not isinstance(brightness,(int,float)) or isinstance(brightness,bool):brightness=.05
    if brightness!=brightness:brightness=.05
    peak=round(255*max(0,min(.1,brightness,ceiling)))
    floor=round(peak*.18)
    result=[]
    for index in range(count):
        phase=((now_ms%120000)/120000+index/max(1,count))*6
        sector=int(phase)%6;fraction=phase-int(phase)
        up=round(floor+(peak-floor)*fraction);down=round(peak-(peak-floor)*fraction)
        result.append(((peak,up,floor),(down,peak,floor),(floor,peak,up),(floor,down,peak),(up,floor,peak),(peak,floor,down))[sector])
    return result

def draw_welcome(ctx,now,theme=None,clock_style="original"):
    ident=theme.get("id","original") if isinstance(theme,dict) else "original"
    styles={"christmas":((.12,.85,.48),"snow"),"easter":((.78,.61,.96),"egg"),
            "anniversary":((1,.46,.66),"heart"),"birthday_self":((1,.72,.3),"gift"),
            "birthday_partner":((1,.52,.75),"gift"),"cyberpunk":((.15,.96,.91),"grid"),
            "lcars":((1,.68,.36),"lcars"),"kitty":((1,.59,.76),"cat"),
            "noir":((.85,.85,.86),"orbit"),"ocean":((.18,.77,.94),"wave"),
            "retro":((.43,1,.51),"pixel")}
    accent,kind=styles.get(ident,((.28,.83,1),"orbit"))
    if ident in ("original","photo"):
        if clock_style=="haute_celestial":accent=(.94,.73,.43)
        elif clock_style=="neon_orrery":accent,kind=(.12,.95,.9),"grid"
        elif clock_style in ("mondaine","great_british_railways"):accent,kind=(1,.18,.16),"rail"
    ctx.rgb(.006,.012,.03).rectangle(-120,-120,240,240).fill()
    def circle(x,y,r,colour):ctx.rgb(*colour).arc(x,y,r,0,math.pi*2,False).fill()
    ctx.line_width=1.5
    for x,y in ((-85,-43),(80,-52),(-92,25),(87,34),(-51,-75),(44,-78)):
        circle(x,y,1,tuple(c*.45 for c in accent))
    ctx.save()
    ctx.translate(math.sin(now/650)*5 if kind=="rail" else 0,0 if kind=="rail" else math.sin(now/350)*2)
    if kind=="snow":
        ctx.rgb(*accent)
        for i in range(6):
            angle=i*math.pi/3;x=math.cos(angle);y=math.sin(angle)
            ctx.move_to(0,-15).line_to(x*42,-15+y*42)
            for side in (-1,1):
                a=angle+side*.7;ctx.move_to(x*27,-15+y*27).line_to(x*27-math.cos(a)*12,-15+y*27-math.sin(a)*12)
        ctx.stroke()
    elif kind=="egg":
        for x,y,colour in ((-34,-9,accent),(0,-22,(1,.79,.46)),(34,-9,(.5,.91,.82))):
            ctx.save();ctx.translate(x,y);ctx.scale(13,21);circle(0,0,1,colour);ctx.restore()
            ctx.line_width=3;ctx.rgb(.96,.91,.98).move_to(x-10,y).line_to(x+10,y).stroke()
    elif kind=="heart":
        circle(-14,-25,20,accent);circle(14,-25,20,accent)
        ctx.rgb(*accent).move_to(-33,-20).line_to(0,25).line_to(33,-20).close_path().fill()
    elif kind=="gift":
        ctx.rgb(*accent).round_rectangle(-30,-34,60,54,5).fill()
        ctx.rgb(1,.9,.63).rectangle(-4,-35,8,56).fill().rectangle(-30,-13,60,7).fill()
        ctx.line_width=3;ctx.arc(-10,-39,10,0,math.pi*2,False).stroke().arc(10,-39,10,0,math.pi*2,False).stroke()
    elif kind=="cat":
        circle(0,-15,30,(1,.95,.96))
        for side in (-1,1):ctx.rgb(1,.95,.96).move_to(side*29,-21).line_to(side*27,-53).line_to(side*7,-39).close_path().fill()
        circle(-11,-17,2,(.12,.08,.13));circle(11,-17,2,(.12,.08,.13));circle(0,-9,3,(1,.78,.29))
        circle(24,-37,8,accent);circle(36,-37,8,accent);circle(30,-37,4,(.9,.22,.42))
    elif kind=="wave":
        for row in range(3):
            ctx.rgb(*accent).move_to(-68,0)
            for i in range(25):
                x=-68+i*136/24;ctx.line_to(x,-28+row*15+math.sin(x/18+now/650)*7)
            ctx.stroke()
    elif kind=="lcars":
        for row in range(4):ctx.rgb(*(accent if row%2 else (.68,.58,.94))).round_rectangle(-73,-53+row*19,29,14,6).fill()
        ctx.rgb(*accent).round_rectangle(-36,-53,107,12,6).fill().round_rectangle(-36,18,107,12,6).fill()
        circle(20,-11,18,(.68,.58,.94));circle(20,-11,12,(.006,.012,.03))
    elif kind=="pixel":
        for x,y in ((0,-36),(-9,-27),(0,-27),(9,-27),(-18,-18),(-9,-18),(0,-18),(9,-18),(18,-18),(-18,-9),(18,-9)):
            ctx.rgb(*accent).rectangle(x-3,y-3,6,6).fill()
    elif kind=="rail":
        ctx.rgb(*accent).round_rectangle(-54,-43,108,62,9).fill()
        for x in (-32,-7,18):ctx.rgb(.82,.94,1).round_rectangle(x,-31,18,23,3).fill()
        for x in (-32,32):circle(x,22,7,(.82,.87,.91))
        ctx.line_width=2;ctx.rgb(*accent).move_to(-70,32).line_to(70,32).stroke()
    else:
        ctx.rgb(*accent).arc(0,-16,35,0,math.pi*2,False).stroke()
        if kind=="grid":
            for x in (-17,0,17):ctx.move_to(x,-44).line_to(x,12)
            for y in (-33,-16,1):ctx.move_to(-28,y).line_to(28,y)
            ctx.stroke()
        else:
            circle(-8,-23,19,tuple(c*.32 for c in accent));circle(-13,-28,9,tuple(c*.65 for c in accent))
        ctx.save();ctx.translate(0,-16);ctx.scale(1,.36);ctx.arc(0,0,70,0,math.pi*2,False).stroke();ctx.restore()
        angle=now/650;x=math.cos(angle)*70;y=-16+math.sin(angle)*25
        ctx.rgb(*accent).move_to(x,y-7).line_to(x+5,y+5).line_to(x,y+2).line_to(x-5,y+5).close_path().fill()
    ctx.restore()
    ctx.font_size=18;ctx.rgb(*accent).move_to(0,72).text("WELCOME BACK")
