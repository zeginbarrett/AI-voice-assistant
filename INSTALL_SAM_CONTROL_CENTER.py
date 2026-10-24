"""Safe, offline install of the SAM Windows Control Center into an existing SAM v5 tree."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import os,re,shutil,sys

SRC=Path(__file__).resolve().parent


def find_roots():
    check=[SRC.parent,Path.cwd(),Path.home()/'Downloads',Path.home()/'Desktop',Path.home()/'Documents']
    seen=set()
    for d in check:
        for root in [d,*([] if not d.is_dir() else list(d.glob('SAM*')) + list(d.glob('AI-voice-assistant*')))]:
            if not root.is_dir():continue
            candidates=[root]+list(root.glob('SAM*'))+list(root.glob('AI-voice-assistant*'))
            for c in candidates:
                key=str(c.resolve())
                if key not in seen:
                    seen.add(key)
                    if (c/'windows'/'sam_pc_wake.py').is_file() and (c/'START_SAM.bat').is_file():yield c


def patch_brain(text):
    if 'sam_control_agent.start(sys.modules[__name__])' in text:return text
    if 'def main():' not in text or 'def read_auth(' not in text:raise ValueError('Unexpected SAM brain source; not changing it')
    def one(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unable to find unique SAM insertion point: '+old[:50])
        text=text.replace(old,new,1)
    one('import sam_continuous_alarm\n','import sam_continuous_alarm\nimport sam_control_agent\nimport sys\n') if 'import sam_continuous_alarm\n' in text else one('import sam_alarms\n','import sam_alarms\nimport sam_control_agent\nimport sys\n')
    one("LOG.info('FIRMWARE VERIFIED: %s',sess.firmware)","LOG.info('FIRMWARE VERIFIED: %s',sess.firmware)\n                    sam_control_agent.apply_led(sess)")
    one("    listener=StreamServer(('0.0.0.0',stream_port),StreamHandler)","    sam_control_agent.start(sys.modules[__name__])\n    listener=StreamServer(('0.0.0.0',stream_port),StreamHandler)")
    return text

LED_CODE=r'''
// SAM user light effects. Frame: 'J' + [mode,r,g,b,brightness,speed].
// The microphone/audio stream protocol and hardware pins are unchanged.
static uint8_t samLedMode=0,samLedR=20,samLedG=110,samLedB=255,samLedBright=75,samLedSpeed=45;
static uint32_t samLedSeed=314159;
static inline uint8_t samClamp(int n){return (uint8_t)constrain(n,0,255);}
static void samPixel(int idx, int r,int g,int b){ring.setPixelColor(idx,ring.Color(samClamp(r),samClamp(g),samClamp(b)));}
static void samLeds(){
  uint32_t t=millis();
  float speed=(float)max(1,(int)samLedSpeed);
  float cycles=(t/1000.0f)*(0.25f+speed/65.0f);
  ring.setBrightness((uint8_t)constrain((int)samLedBright*255/100,0,255));
  uint8_t r=samLedR,g=samLedG,b=samLedB;
  if(samLedMode==1){ring.clear();ring.show();return;}
  if(samLedMode==2){paint(r,g,b);return;}
  if(samLedMode==3 || samLedMode==8 || samLedMode==11){
    float breath=.18f+.82f*(.5f+.5f*sinf(6.283185f*cycles));
    if(samLedMode==11){r=0;g=110;b=255;}
    paint((uint8_t)(r*breath),(uint8_t)(g*breath),(uint8_t)(b*breath));return;
  }
  if(samLedMode==6){ // Flash at <= 2 Hz to avoid very fast strobe patterns.
    uint32_t period=(uint32_t)(700-(samLedSpeed*2));
    if(period<500)period=500;
    bool lit=(t%period)<(period/2);
    if(lit)paint(r,g,b);else paint(0,0,0);return;
  }
  if(samLedMode==10){ // Warm candle flicker.
    uint8_t intensity=(uint8_t)random(90,220);
    paint(intensity,intensity/3,4);return;
  }
  for(int i=0;i<NUM_LEDS;i++){
    if(samLedMode==4 || samLedMode==12){
      uint16_t h=(uint16_t)((i*65536UL/NUM_LEDS)+(uint32_t)(cycles*10500))&65535;
      ring.setPixelColor(i,ring.gamma32(ring.ColorHSV(h,255,255)));
    }else if(samLedMode==5){
      uint32_t hue=(uint32_t)((t/(uint32_t)max(40,650-(int)samLedSpeed*5))+i*3)*20011;
      ring.setPixelColor(i,ring.gamma32(ring.ColorHSV((uint16_t)hue,245,255)));
    }else if(samLedMode==7){
      float pos=fmodf(cycles*2.0f,NUM_LEDS);
      int idx=(int)pos;
      if(i==idx)samPixel(i,r,g,b);
      else if(i==(idx+NUM_LEDS-1)%NUM_LEDS)samPixel(i,r/4,g/4,b/4);
      else samPixel(i,0,0,0);
    }else if(samLedMode==9){
      bool flash=(random(0,100)<18);
      samPixel(i,flash?r:0,flash?g:0,flash?b:0);
    }else if(samLedMode==13){
      int idx=((uint32_t)(cycles*2))%NUM_LEDS;
      int dist=(idx+NUM_LEDS-i)%NUM_LEDS;
      int divisor=dist==0?1:dist==1?3:dist==2?8:30;
      samPixel(i,r/divisor,g/divisor,b/divisor);
    }else{samPixel(i,r,g,b);}
  }
  ring.show();
}
'''


def patch_firmware(text):
    if 'static uint8_t samLedMode=0' in text:return text
    old='void tickLeds(){\n'
    if text.count(old)!=1 or "if(cmd=='G'){" not in text:raise ValueError('Unexpected firmware source; refusing to overwrite')
    text=text.replace(old,LED_CODE+'\n'+old+'  if(samLedMode!=0){if(millis()-lastLed<45)return;lastLed=millis();samLeds();return;}\n  ring.setBrightness(80);\n',1)
    marker="    else if(cmd=='I')phase=IDLE;"
    payload='''    else if(cmd=='J'){
      uint8_t data[6]={0,0,0,0,0,0};
      if(upstream.readBytes((char*)data,6)==6 && data[0]<=13 && data[4]<=100 && data[5]<=100){
        samLedMode=data[0];samLedR=data[1];samLedG=data[2];samLedB=data[3];
        samLedBright=data[4];samLedSpeed=data[5];
        Serial.printf("[LED] mode=%u brightness=%u speed=%u\\n",samLedMode,samLedBright,samLedSpeed);
      }
    }
'''
    if marker not in text:raise ValueError('Missing command insertion point')
    text=text.replace(marker,payload+marker,1)
    if 'SAM-V5-HANDSFREE-MUSIC' in text:text=text.replace('SAM-V5-HANDSFREE-MUSIC','SAM-V5-HANDSFREE-MUSIC-LED1')
    return text


def install(root):
    win=root/'windows'; brain=win/'sam_pc_wake.py'; firmware=root/'SAM_PC_Wake'/'SAM_PC_Wake.ino'
    if not firmware.exists():raise ValueError('Firmware not found in SAM installation')
    newbrain=patch_brain(brain.read_text(encoding='utf-8'))
    newfirm=patch_firmware(firmware.read_text(encoding='utf-8'))
    backup=root/'sam_control_backups'/datetime.now().strftime('%Y%m%d_%H%M%S')
    backup.mkdir(parents=True,exist_ok=True)
    for p in (brain,firmware):
        dst=backup/p.relative_to(root);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    for src,name in [
        (SRC/'app'/'sam_control_agent.py','windows/sam_control_agent.py'),
        (SRC/'app'/'sam_control_center.py','windows/sam_control_center.py')]:
        dest=root/name;shutil.copy2(src,dest)
    ui=win/'sam_panel_ui';ui.mkdir(exist_ok=True)
    for file in (SRC/'panel_ui').iterdir():
        if file.is_file():shutil.copy2(file,ui/file.name)
    brain.write_text(newbrain,encoding='utf-8')
    firmware.write_text(newfirm,encoding='utf-8')
    (root/'START_SAM_CONTROL_CENTER.bat').write_text('@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nset "SAM_PY="\r\nif exist "windows\\python_path.txt" set /p SAM_PY=<"windows\\python_path.txt"\r\nif defined SAM_PY if exist "%SAM_PY%" ("%SAM_PY%" "windows\\sam_control_center.py" & exit /b %errorlevel%)\r\npy -3 "windows\\sam_control_center.py"\r\nif errorlevel 1 (python "windows\\sam_control_center.py")\r\npause\r\n',encoding='utf-8')
    return backup


def main():
    if os.name!='nt':
        print('This installer is for Windows PCs running SAM.');return 2
    paths=list(find_roots())
    if paths:
        print('Found SAM installations:')
        for i,p in enumerate(paths,1):print(f'  {i}. {p}')
        answer=input('Choose a number [1]: ').strip() or '1'
        if not answer.isdigit() or not 1<=int(answer)<=len(paths):raise ValueError('Invalid choice')
        root=paths[int(answer)-1]
    else:
        root=Path(input('Enter the existing SAM installation folder: ').strip(' "'))
    if not (root/'windows'/'sam_pc_wake.py').is_file():raise ValueError('SAM Windows brain not found')
    b=install(root)
    print('SUCCESS. SAM Control Center installed in:',root)
    print('Original SAM source backed up at:',b)
    print('Start with:',root/'START_SAM_CONTROL_CENTER.bat')
    print('You must flash the updated ESP32 firmware once to enable LED effects.')
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:print('INSTALL FAILED safely:',exc);sys.exit(1)

