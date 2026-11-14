"""Back up the selected new device before flashing. Never selects a port automatically."""
import argparse,datetime,hashlib,json,subprocess,sys
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--port',required=True);ap.add_argument('--image',type=Path,required=True);args=ap.parse_args()
manifest=json.loads(args.image.with_name('manifest.json').read_text(encoding='utf-8'))
if manifest.get('offset')!=0 or hashlib.sha256(args.image.read_bytes()).hexdigest()!=manifest['sha256']:
 raise SystemExit('Image checksum/offset does not match the manifest')
if 'Waveshare ESP32-S3-LCD-1.85' not in manifest.get('board',''):raise SystemExit('Unexpected board manifest')
print('Target:',args.port,'Waveshare ESP32-S3 LCD 1.85 ONLY. Do not select the Spaceagon.')
if input('Type FLASH to back up and replace this device firmware: ')!='FLASH':raise SystemExit('Cancelled')
folder=Path('spaceport-factory-backup-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'));folder.mkdir()
backup=folder/'factory-16MB.bin'
base=[sys.executable,'-m','esptool','--chip','esp32s3','--port',args.port,'--baud','460800']
detected=subprocess.run(base+['flash_id'],check=True,capture_output=True,text=True)
print(detected.stdout)
if 'Detected flash size: 16MB' not in detected.stdout:raise SystemExit('Expected 16MB flash; no image written')
subprocess.run(base+['read_flash','0','0x1000000',str(backup)],check=True)
if backup.stat().st_size!=0x1000000:raise SystemExit('Backup size wrong; flashing cancelled')
subprocess.run(base+['verify_flash','0',str(backup)],check=True)
(folder/'SHA256.txt').write_text(hashlib.sha256(backup.read_bytes()).hexdigest()+'  '+backup.name+'\n')
subprocess.run(base+['write_flash','--flash_size','16MB','0',str(args.image)],check=True)
subprocess.run(base+['verify_flash','0',str(args.image)],check=True)
print('Installed and verified. Factory backup:',backup.resolve())
print('Next run provision.py with this same port. Backups may contain factory credentials; keep them private.')
