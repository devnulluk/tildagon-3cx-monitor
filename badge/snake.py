"""Small self-playing Snake; a Hamiltonian safety order prevents collisions."""
W,H=16,6
CYCLE=((0,0),)+tuple((x,y) for y in range(H) for x in (range(1,W) if y%2==0 else range(W-1,0,-1)))+tuple((0,y) for y in range(H-1,0,-1))
INDEX={point:i for i,point in enumerate(CYCLE)}
class Snake:
    def __init__(self,seed=1):
        self.body=list(range(5,-1,-1));self.seed=seed;self.score=0;self.ticks=0;self.food=0;self._food()
    def _food(self):
        self.seed=(1664525*self.seed+1013904223)&0xffffffff
        target=(self.body[0]+4+self.seed%(len(CYCLE)-len(self.body)-3))%len(CYCLE)
        while target in self.body:target=(target+1)%len(CYCLE)
        self.food=target
    def step(self):
        head=self.body[0];tail=self.body[-1];size=len(CYCLE);gap=(tail-head)%size;distance=(self.food-head)%size
        x,y=CYCLE[head];choices=[]
        for point in ((x+1,y),(x,y+1),(x-1,y),(x,y-1)):
            candidate=INDEX.get(point)
            if candidate is None:continue
            advance=(candidate-head)%size
            if 0<advance<=gap and advance<=distance and candidate not in self.body[:-1]:choices.append((advance,candidate))
        candidate=max(choices)[1] if choices else (head+1)%size
        eating=candidate==self.food
        self.body.insert(0,candidate)
        if not eating or len(self.body)>18:self.body.pop()
        if eating:self.score+=1;self._food()
        self.ticks+=1
        return eating
    def points(self):return tuple((CYCLE[i][0]+1,CYCLE[i][1]+2) for i in self.body)
    def apple(self):return (CYCLE[self.food][0]+1,CYCLE[self.food][1]+2)
