"""Build a credential-free factory image. Does not open a serial port."""
import hashlib,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,'-m','platformio','run','-d',str(root)],check=True)
subprocess.run([sys.executable,'-m','platformio','run','-d',str(root),'-t','buildfs'],check=True)
home=Path(os.environ.get('PLATFORMIO_CORE_DIR',Path.home()/'.platformio'))
build=root/'.pio/build/spaceport'
out=root/'release';out.mkdir(exist_ok=True)
esptool=home/'packages/tool-esptoolpy/esptool.py'
subprocess.run([sys.executable,str(esptool),'--chip','esp32s3','merge_bin','--flash_mode','qio','--flash_freq','80m','--flash_size','16MB','-o',str(out/'spaceport-0.1.0.bin'),'0x0',str(build/'bootloader.bin'),'0x8000',str(build/'partitions.bin'),'0xe000',str(home/'packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin'),'0x10000',str(build/'firmware.bin'),'0xa10000',str(build/'littlefs.bin')],check=True)
image=out/'spaceport-0.1.0.bin'
manifest={'version':'0.1.0','board':'Waveshare ESP32-S3-LCD-1.85 non-touch, 16MB flash / 8MB PSRAM','offset':0,'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'bytes':image.stat().st_size,'physical_validation':False}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for name in ['flash.py','provision.py']:shutil.copy2(root/'tools'/name,out/name)
shutil.copy2(root/'README.md',out/'README.md')
shutil.copy2(root/'requirements-install.txt',out/'requirements-install.txt')
archive=out/'spaceport-0.1.0.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for f in out.iterdir():
  if f.is_file() and f.suffix!='.zip':z.write(f,f.name)
 for folder in ['docs','data/sounds']:
  for f in (root/folder).rglob('*'):
   if f.is_file():z.write(f,str(f.relative_to(root)))
 for name in ['NOTICE','LICENSE-APACHE-2.0.txt']:z.write(root/name,name)
print('Ready:',archive)
