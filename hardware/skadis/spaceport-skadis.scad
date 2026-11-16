// Original Spaceport carrier geometry, millimetres, viewed from FRONT.
part="carrier";
$fn=64;
hook_width=4.4;
mounts=[[14.90,15.73],[-14.10,15.73],[0,-21.27]];
module bar(a,b,w=8){hull(){translate(a)cylinder(d=w,h=3);translate(b)cylinder(d=w,h=3);}}
module carrier(){difference(){union(){
 for(p=mounts){bar([0,3],p);translate(p)cylinder(d=6,h=9);}
 for(x=[-20,20])bar([0,3],[x,40]);
 translate([-35,30,0])cube([70,24,3]);
 bar([0,-21.27],[0,-47],10);
 translate([-20,-62,0])cube([40,30,3]);
 for(x=[-20,18])translate([x,-62,3])cube([2,30,7]);
 translate([-20,-62,3])cube([40,2,7]);
 translate([0,42,3])linear_extrude(.6)text("SPACEPORT",size=4,halign="center",valign="center");
 }
 for(p=mounts)translate([p[0],p[1],-1])cylinder(d=2.4,h=12);
 for(x=[-20,20])for(y=[36,48])translate([x+5.8,y,-1])cylinder(d=3.4,h=6);
 for(x=[-12,12])for(y=[-59,-35])translate([x-1.6,y-1.1,-1])cube([3.2,2.2,6]);
 translate([0,-43,-1])cylinder(d=3.4,h=6);
 translate([0,-43,1.4])cylinder(d1=3.4,d2=6.6,h=1.7);
 }}
module hook(){difference(){union(){
 translate([0,-8,0])cube([14,20,3]);
 translate([0,-3,-15.7])cube([hook_width,3,16.2]);
 hull(){translate([0,-3,-15.7])cube([hook_width,10,2.4]);translate([0,7,-15.7])cube([hook_width,2,1]);}
 }
 for(y=[-4,8])translate([8,y,-1])cylinder(d=3.4,h=6);
 }}
module bumper(){difference(){cylinder(d=12,h=11);translate([0,0,4])cylinder(d=2.8,h=8);}}
if(part=="carrier")carrier();
if(part=="hook")translate([3,0,0])rotate([0,-90,0])hook();
if(part=="bumper")bumper();
if(part=="assembly"){
 color("#16394b")carrier();
 for(x=[-20,20])color("#12bcc5")translate([x-2.2,40,-3])hook();
 color("#12bcc5")translate([0,-43,-11])bumper();
 color("#141b25")translate([0,0,9])cylinder(d=50,h=4);
 color("#263650")translate([0,0,13])cylinder(d=55,h=1.7);
 color("#4bbbd4")translate([0,0,14.8])cylinder(d=46.08,h=.2);
 color("#222222")translate([-15,-57,3])cube([30,20,7]);
}
