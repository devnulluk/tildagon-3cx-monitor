"""Read safe Spaceport status without resetting ESP32 USB Serial/JTAG."""
import argparse,json,time
import serial
ap=argparse.ArgumentParser();ap.add_argument('--port',required=True);args=ap.parse_args()
p=serial.Serial(port=None,baudrate=115200,timeout=.25,write_timeout=3)
p.rts=False;p.dtr=False;p.port=args.port
try:
 p.open();p.rts=False;p.dtr=True;time.sleep(.5);p.reset_input_buffer();p.write(b'{"command":"status"}\n');p.flush();deadline=time.monotonic()+6
 while time.monotonic()<deadline:
  line=p.readline().decode('utf-8','replace').strip()
  if line.startswith('SPACEPORT_STATUS '):
   print(json.dumps(json.loads(line.split(' ',1)[1]),indent=2));break
 else:raise SystemExit('No Spaceport status response')
finally:
 if p.is_open:p.rts=False;p.dtr=False;p.close()
