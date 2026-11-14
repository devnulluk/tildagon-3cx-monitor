"""Provision one Spaceport over USB; secrets are entered locally and never logged."""
import argparse,getpass,json,secrets,ssl,time
from pathlib import Path
from urllib.parse import urlsplit
import serial

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',required=True)
    ap.add_argument('--badge-config',type=Path,help='Optional existing private Spaceagon config; never uploaded to GitHub')
    ap.add_argument('--ca',type=Path,help='PEM or DER server trust root, required without --badge-config')
    args=ap.parse_args()
    cfg=json.loads(args.badge_config.read_text(encoding='utf-8')) if args.badge_config else {}
    url=cfg.get('bridge_url') or input('Bridge HTTPS origin: ').strip()
    parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.path not in ('','/') or parts.query or parts.fragment:
        raise SystemExit('Use an HTTPS origin without a path or embedded credentials')
    ca_path=args.ca or (args.badge_config.parent/cfg.get('ca_file','ca.der') if args.badge_config else None)
    if ca_path is None:raise SystemExit('--ca is required')
    data=ca_path.read_bytes()
    cert=data.decode() if data.startswith(b'-----BEGIN') else ssl.DER_cert_to_PEM_cert(data)
    secret=cfg.get('token') or getpass.getpass('Read-only bridge token: ')
    key=secrets.token_urlsafe(24)
    partners=cfg.get('partner_numbers') or []
    payload={'ssid':input('Wi-Fi SSID: '),'password':getpass.getpass('Wi-Fi password: '),
             'origin':url.rstrip('/'),'token':secret,'ca':cert,'web_key':key,
             'partner_number':partners[0] if partners else getpass.getpass('Partner caller number (optional, hidden): '),
             'partner_name':cfg.get('partner_name','Partner'),'partner_surname':cfg.get('partner_surname',cfg.get('partner_last_name',''))}
    encoded=(json.dumps(payload,separators=(',',':'))+'\n').encode()
    if len(encoded)>8192:raise SystemExit('Configuration exceeds device limit')
    with serial.Serial(args.port,115200,timeout=1,write_timeout=5) as port:
        time.sleep(2);port.reset_input_buffer();port.write(encoded);port.flush()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            line=port.readline()
            if b'SETUP_SAVED' in line:break
            if b'SETUP_INVALID' in line:raise SystemExit('Device rejected configuration; no values printed')
        else:raise SystemExit('No setup acknowledgement; check USB and repeat')
    receipt=Path('spaceport-access.local.json')
    receipt.write_text(json.dumps({'username':'spaceport','password':key,'hostname':'spaceport','note':'Find IP in your router or device idle footer'},indent=2)+'\n')
    print('Configuration saved. Web control credentials are in '+str(receipt.resolve()))

if __name__=='__main__':main()
