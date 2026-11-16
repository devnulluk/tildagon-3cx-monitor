// Compact Spaceport carrier, original geometry, mm. Viewed from FRONT.
// Existing M2 mounts hold the device; nothing clamps the glass.
part="carrier"; // carrier, hook_left, hook_right, foot, assembly
$fn=64;
hook_width=4.4;
mounts=[[14.90,15.73],[-14.10,15.73],[0,-21.27]];
module bar(a,b,w=7){hull(){translate(a)cylinder(d=w,h=3);translate(b)cylinder(d=w,h=3);}}
module countersink(p){translate([p[0],p[1],-1])cylinder(d=3.4,h=6);translate([p[0],p[1],1.4])cylinder(d1=3.4,d2=6.6,h=1.7);}
module carrier(){difference(){intersection(){cylinder(d=54,h=9);union(){
 for(p=mounts){bar([0,3],p);translate(p)cylinder(d=6,h=9);}
 for(side=[-1,1]){
  translate([side<0?-24:8,-10,0])cube([16,24,3]);
  bar([0,3],[side*16,3]);
  bar([0,-21.27],[side*13,-16]);
  translate([side*13,-16,0])cylinder(d=8,h=3);
 }
 }}
 for(p=mounts)translate([p[0],p[1],-1])cylinder(d=2.4,h=12);
 for(side=[-1,1]){
  for(y=[-4,8])countersink([side*14.2,y]);
  countersink([side*13,-16]);
 }
 }}
// Left hook in assembly coordinates before placement: neck X 0..4.4.
module hook(){difference(){union(){
 translate([0,-8,0])cube([14,20,3]);
 translate([0,-3,-15.7])cube([hook_width,3,16.2]);
 hull(){translate([0,-3,-15.7])cube([hook_width,10,2.4]);translate([0,7,-15.7])cube([hook_width,2,1]);}
 }
 for(y=[-4,8])translate([8,y,-1])cylinder(d=3.4,h=6);
 }}
module foot(){difference(){cylinder(d=8,h=11);translate([0,0,4])cylinder(d=2.8,h=8);}}
if(part=="carrier")carrier();
if(part=="hook_left")translate([3,0,0])rotate([0,-90,0])hook();
if(part=="hook_right")translate([15.7,0,0])rotate([0,90,0])mirror([1,0,0])hook();
if(part=="foot")foot();
if(part=="assembly"){
 color("#16394b")carrier();
 color("#12bcc5")translate([-22.2,0,-3])hook();
 color("#12bcc5")mirror([1,0,0])translate([-22.2,0,-3])hook();
 for(x=[-13,13])color("#12bcc5")translate([x,-16,-11])foot();
 color("#141b25")translate([0,0,9])cylinder(d=50,h=4);
 color("#263650")translate([0,0,13])cylinder(d=55,h=1.7);
 color("#4bbbd4")translate([0,0,14.8])cylinder(d=46.08,h=.2);
}
