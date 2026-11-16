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

def draw_welcome(ctx,now,bunny):
    ctx.rgb(.006,.012,.03).rectangle(-120,-120,240,240).fill()
    ctx.rgb(.20,.47,.59)
    for x,y in ((-71,-24),(68,-35),(-82,29),(79,43),(-51,-52),(46,-51)):
        ctx.arc(x,y,1.4,0,6.28318531,False).fill()
    ctx.font_size=18;ctx.rgb(.68,.89,.96).move_to(0,-73).text("WELCOME BACK")
    bunny(ctx,now)
