// One-piece screen mount. mm; device front is +Z, pegboard behind -Z.
part="print"; // print, assembled, preview
$fn=64;
slot_pitch=40;
slot_width=5;
hook_width=4.2;
board_thickness=5;
stand_off=7;
upper_slot_y=15.5;
lower_slot_y=upper_slot_y-slot_pitch;
mounts=[[14.90,15.73],[-14.10,15.73],[0,-21.27]];
assert(hook_width<slot_width);
module bar(a,b,w=7){hull(){translate(a)cylinder(d=w,h=3);translate(b)cylinder(d=w,h=3);}}
module mount(){difference(){union(){
 // Flat 3mm carrier: the device already has raised mounting bosses.
 for(p=mounts)bar([0,3],p);
 bar([0,3],[0,lower_slot_y],5);
 bar([0,3],[0,10],7);
 // Hook neck sits at the bottom of the upper 15mm slot.
 translate([-hook_width/2,8,-stand_off-board_thickness-2.6])cube([hook_width,3,stand_off+board_thickness+3.6]);
 // Retaining lip extends above the slot; insert at an angle, then lower.
 hull(){
  translate([-hook_width/2,8,-stand_off-board_thickness-2.6])cube([hook_width,17,2.4]);
  translate([-hook_width/2,25,-stand_off-board_thickness-2.6])cube([hook_width,2,1.2]);
 }
 // Short tapered locating peg: enters lower slot, no separate fixing.
 // Integral shoulder rests on the pegboard face to keep the screen upright.
 translate([-4,lower_slot_y-2,-stand_off])cube([8,2.5,stand_off+.3]);
 hull(){
  translate([-2.1,lower_slot_y-1.4,-8])cube([4.2,2.8,8.5]);
  translate([-1.5,lower_slot_y-1,-11.5])cube([3,2,1]);
 }
 }
 for(p=mounts)translate([p[0],p[1],-1])cylinder(d=2.4,h=5);
 }}
if(part=="assembled")mount();
// Side orientation puts layer lines along the hook profile. Use supports + brim.
if(part=="print")translate([14.6,0,17.6])rotate([0,-90,0])mount();
if(part=="preview"){
 color("#16394b")mount();
 color("#141b25")translate([0,0,3])cylinder(d=50,h=4);
 color("#263650")translate([0,0,7])cylinder(d=55,h=1.7);
 color("#4bbbd4")translate([0,0,8.8])cylinder(d=46.08,h=.2);
}
