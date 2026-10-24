/*
  SAM PC-WAKE / Waveshare ESP32-S3-AUDIO-Board - standalone firmware
  ESP32 = 16-bit standard I2S full-duplex ES7210 + ES8311 -> stereo PCM WiFi + speaker.
  PC = "Hey Sam" detection via local Whisper + Ollama + speech synthesis.
  NO ESP-SR or on-device wake model, no Home Assistant; PC streams SD music and offline TTS.
  I2C: SDA11 SCL10; ES7210 0x40 ES8311 0x18 TCA9555 0x20
  I2S: MCLK12 BCLK13 LRCLK14 ADC15 DAC16; 7 RGB WS2812 GPIO38.
  Sound over LAN is unencrypted: trusted private Wi-Fi only.
*/
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ESP_I2S.h>
#include <Adafruit_NeoPixel.h>
#include <cmath>
#include <FS.h>
#include <SD_MMC.h>
#include <vector>
#include <freertos/semphr.h>
#include "sam_config.h"  // generated locally by the one-click setup, never shipped

static constexpr uint8_t EXP=0x20, MIC=0x40, DAC=0x18;
static constexpr int RATE=16000, RGB=38, NUM_LEDS=7;
static constexpr uint16_t FRAMES_PER_PACKET=512;
static constexpr uint32_t LOG_INTERVAL=6000;
static constexpr const char *FW_VER="SAM-V5-HANDSFREE-MUSIC-LED1";
I2SClass audio;
Adafruit_NeoPixel ring(NUM_LEDS,RGB,NEO_RGB+NEO_KHZ800);
WiFiClient upstream;
// The ES7210 supplies MIC1 and MIC2 on SDOUT1 in non-TDM Philips I2S mode.
// ESP32-S3 is the ONLY clock master (MCLK12/BCLK13/LRCLK14). Full-duplex
// TX/RX channels share ONE ESP32 I2S peripheral. Speaker uses ES8311 on GPIO16.
// Send actual interleaved 16-bit stereo at 16 kHz to Windows. No resampling
// and no invented zero padding.
static int16_t micStereo[FRAMES_PER_PACKET*2];
static uint8_t lastKey=0xFF;
static volatile bool ampOn=false;
static bool audioReady=false;
static uint32_t lastLed=0, lastLog=0, lastConnection=0;
static uint64_t transmittedFrames=0;
static uint32_t samplePeak=0, sampleNonzero=0, sampleCount=0;
static uint32_t sampleZeroPhases[8]={0}, samplePhaseCount[8]={0};
enum Phase: uint8_t { IDLE, LISTEN, THINK, REPLY, ERROR_PHASE };
static volatile Phase phase=IDLE;
static SemaphoreHandle_t txMutex=nullptr;
static bool sdReady=false;
static std::vector<String> songs;
static constexpr uint16_t SD_HTTP_PORT=8770;
static constexpr uint16_t MUSIC_STREAM_PORT=8771;
static WiFiServer sdHttp(SD_HTTP_PORT), musicStream(MUSIC_STREAM_PORT);
// Also permit ordinary C++ syntax checkers (Arduino IDE generates .ino prototypes).
bool expPin(uint8_t pin,bool high);
void amp(bool on);

static volatile uint8_t speakerVolume=75;    // 0..100, applies to both SAM and music
static volatile bool musicActive=false;
static inline int16_t scalePlayback(int16_t sample){
  int32_t v=(int32_t)sample*(int32_t)speakerVolume/100;
  if(v>32767)v=32767;if(v<-32768)v=-32768;
  return (int16_t)v;
}
// Read-only FAT32 1-bit SDMMC. The TCA9555 EXIO3 SD_CS is held HIGH,
// matching the previously working standalone SAM Shuffle implementation.
void findSongs(const String& folder, int depth){
  if(depth>5 || songs.size()>=1500) return;
  File dir=SD_MMC.open(folder.c_str());
  if(!dir || !dir.isDirectory())return;
  File child=dir.openNextFile();
  while(child && songs.size()<1500){
    String file=String(child.name());
    String path=file.startsWith("/")?file:(folder=="/"?"/"+file:folder+"/"+file);
    if(child.isDirectory()){
      child.close();findSongs(path,depth+1);
    }else{
      String lower=path;lower.toLowerCase();
      if(lower.endsWith(".mp3"))songs.push_back(path);
      child.close();
    }
    child=dir.openNextFile();
  }
  dir.close();
}
void replyHeader(WiFiClient& client, int code, const char* contentType){
  client.print(code==200?"HTTP/1.1 200 OK\r\n":"HTTP/1.1 404 Not Found\r\n");
  client.print("Connection: close\r\nCache-Control: no-store\r\nContent-Type: ");
  client.print(contentType);client.print("\r\n\r\n");
}
void sdTask(void*){
  for(;;){
    WiFiClient client=sdHttp.available();
    if(!client){vTaskDelay(pdMS_TO_TICKS(15));continue;}
    client.setTimeout(1300);
    String request=client.readStringUntil('\n');request.trim();
    bool auth=false;
    uint32_t started=millis();
    while(client.connected() && millis()-started<1400){
      if(!client.available()){vTaskDelay(pdMS_TO_TICKS(5));continue;}
      String line=client.readStringUntil('\n');line.trim();
      if(line.length()==0)break;
      if(line.startsWith("X-Sam-Token: ")) auth=line.substring(13).equals(String(SAM_TOKEN));
    }
    if(!auth){client.print("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");client.stop();continue;}
    if(request.startsWith("GET /library ")){
      replyHeader(client,200,"text/plain; charset=utf-8");
      if(!sdReady)client.print("ERROR\tSD unavailable\n");
      else for(unsigned i=0;i<songs.size()&&client.connected();i++){
        client.print(i);client.print('\t');client.println(songs[i]);
        if((i&31u)==0u)vTaskDelay(1);
      }
    }else if(request.startsWith("GET /track/")){
      int off=11;int end=request.indexOf(' ',off);
      String arg=request.substring(off,end<0?request.length():end);
      bool digits=arg.length()>0 && arg.length()<=5;
      for(unsigned i=0;i<arg.length();i++)if(!isDigit(arg[i]))digits=false;
      int idx=digits?arg.toInt():-1;
      if(sdReady && idx>=0 && idx<(int)songs.size()){
        File file=SD_MMC.open(songs[idx].c_str(),FILE_READ);
        if(file){replyHeader(client,200,"audio/mpeg");
          uint8_t buf[2048];
          while(file.available()&&client.connected()){
            size_t n=file.read(buf,sizeof(buf));if(!n)break;
            if(client.write(buf,n)!=n)break;
            vTaskDelay(1);
          }
          file.close();
        }else replyHeader(client,404,"text/plain");
      }else replyHeader(client,404,"text/plain");
    }else replyHeader(client,404,"text/plain");
    delay(25);client.stop();
  }
}

// Separate Wi-Fi PCM stream for media audio. Receives stereo PCM16 at 16kHz.
// Mic RX on the main task continues to run while music is playing.
void musicTask(void*){
  uint8_t buf[2048];uint32_t lastAudio=0;
  for(;;){
    WiFiClient client=musicStream.available();
    if(!client){vTaskDelay(pdMS_TO_TICKS(20));continue;}
    client.setTimeout(250);
    String line=client.readStringUntil('\n');
    line.trim();
    if(!line.equals("SAMAUDIO1 "+String(SAM_TOKEN))){client.stop();continue;}
    Serial.println("[MUSIC] authenticated 16k PCM stream started");
    musicActive=true;amp(true);lastAudio=millis();
    size_t carry=0;
    while(client.connected()){
      // Stop consuming when SAM is listening or speaking. TCP backpressure
      // naturally pauses ffmpeg without discarding music or drowning the mic.
      if(phase!=IDLE){vTaskDelay(pdMS_TO_TICKS(15));continue;}
      int n=client.read(buf+carry,sizeof(buf)-carry);
      if(n<=0){if(millis()-lastAudio>25000)break;
        vTaskDelay(pdMS_TO_TICKS(5));continue;}
      lastAudio=millis();
      size_t avail=carry+(size_t)n,aligned=avail & ~(size_t)3;
      if(aligned && txMutex && xSemaphoreTake(txMutex,pdMS_TO_TICKS(1200))==pdTRUE){
        // Scale music with the same speaker level as SAM's spoken replies.
        for(size_t k=0;k<aligned;k+=2){
          int16_t v=(int16_t)((uint16_t)buf[k]|((uint16_t)buf[k+1]<<8));
          int16_t w=scalePlayback(v);buf[k]=(uint8_t)w;buf[k+1]=(uint8_t)((uint16_t)w>>8);
        }
        audio.write(buf,aligned);
        xSemaphoreGive(txMutex);
      }
      carry=avail-aligned;
      if(carry)memmove(buf,buf+aligned,carry);
    }
    musicActive=false;client.stop();
    if(phase!=REPLY)amp(false);
    Serial.println("[MUSIC] stream ended");
  }
}


bool regRead(uint8_t addr,uint8_t reg,uint8_t& value){
  Wire.beginTransmission(addr);Wire.write(reg);
  if(Wire.endTransmission(false)!=0)return false;
  if(Wire.requestFrom(addr,(uint8_t)1)!=(uint8_t)1)return false;
  value=(uint8_t)Wire.read();return true;
}
bool regWrite(uint8_t addr,uint8_t reg,uint8_t val){
  Wire.beginTransmission(addr);Wire.write(reg);Wire.write(val);
  return Wire.endTransmission()==0;
}
bool expPin(uint8_t pin,bool high){
  uint8_t out=0,cfg=0,mask=(uint8_t)(1u<<(pin&7));
  const uint8_t outReg=pin<8?0x02:0x03, cfgReg=pin<8?0x06:0x07;
  if(!regRead(EXP,outReg,out)||!regRead(EXP,cfgReg,cfg))return false;
  uint8_t next=high?(out|mask):(out&~mask);
  return regWrite(EXP,outReg,next) && regWrite(EXP,cfgReg,(uint8_t)(cfg&~mask));
}
void amp(bool on){if(ampOn!=on && expPin(8,on))ampOn=on;}

// Exact functional equivalent of stock ESPHome es7210.cpp setup(),
// configured for its working 16-bit / 16 kHz / NON-TDM I2S audio path:
// https://github.com/esphome/esphome/blob/dev/esphome/components/es7210/es7210.cpp
// IMPORTANT: using 0xC3 and MIC12_POWER=0x0F here matches working ESPHome;
// these registers must not be guessed from the TDM experiment.
bool initMic(){
  uint8_t prev=0;if(!regRead(MIC,0x00,prev))return false;
  bool ok=true;
  auto w=[&](uint8_t reg,uint8_t value){ok=regWrite(MIC,reg,value)&&ok;};
  auto u=[&](uint8_t reg,uint8_t mask,uint8_t val){uint8_t before=0;
    if(!regRead(MIC,reg,before)){ok=false;return;}
    w(reg,(uint8_t)((before&~mask)|(mask&val)));};
  w(0x00,0xFF); delay(10);
  w(0x00,0x32);w(0x01,0x3F);
  w(0x09,0x30);w(0x0A,0x30);
  w(0x23,0x2A);w(0x22,0x0A);w(0x20,0x0A);w(0x21,0x2A);
  u(0x08,0x01,0x00); // codec SLAVE, ESP32 clock master
  w(0x40,0xC3); // analog: match ESPHome exactly
  w(0x41,0x70);w(0x42,0x70); // both microphone bias voltages
  w(0x11,0x60); // 16-bit Philips I2S
  w(0x12,0x00); // NOT TDM: MIC1/2 over SDOUT1 (GPIO15)
  // 16 kHz x 256 = 4.096 MHz MCLK; Espressif/ESPHome coefficient:
  // adc_div=1, DLL=1, doubler=1, OSR=0x20, LRCK divider=0x0100
  w(0x02,0xC1);w(0x07,0x20);w(0x04,0x01);w(0x05,0x00);
  // Stock ESPHome configure_mic_gain_() uses these updates.
  for(int k=0;k<4;k++)u((uint8_t)(0x43+k),0x10,0x00);
  w(0x4B,0xFF);w(0x4C,0xFF);
  for(int k=0;k<2;k++){
    u(0x01,0x0B,0x00);w(0x4B,0x00);
    u((uint8_t)(0x43+k),0x10,0x10);
    u((uint8_t)(0x43+k),0x0F,0x08); // 24 dB PGA, as working repo
  }
  for(int k=2;k<4;k++){
    u(0x01,0x15,0x00);w(0x4C,0x00);
    u((uint8_t)(0x43+k),0x10,0x10);
    u((uint8_t)(0x43+k),0x0F,0x08);
  }
  for(int k=0;k<4;k++)w((uint8_t)(0x47+k),0x08);
  w(0x06,0x04); // ESPHome powers down DLL explicitly
  w(0x4B,0x0F);w(0x4C,0x0F);
  w(0x00,0x71);delay(5);w(0x00,0x41);
  Serial.printf("[MIC ES7210] init=%s, codec slave, standard 16-bit, 16kHz, +24dB\n",ok?"OK":"ERROR");
  const uint8_t regs[]={0x00,0x01,0x02,0x04,0x05,0x06,0x08,0x11,0x12,0x40,0x43,0x44,0x4B};
  for(uint8_t reg:regs){uint8_t v=0;if(regRead(MIC,reg,v))Serial.printf("[MIC] reg %02X=%02X\n",reg,v);}
  return ok;
}

// ONE full-duplex I2S channel pair with shared BCLK/LRCLK/MCLK pins. This is
// the ESP-IDF/Arduino equivalent of the working ESPHome master-mic/slave-speaker
// layout; because our standalone firmware can allocate TX+RX together, no
// second peripheral needs to drive the same physical clock pins.
bool captureMode(){
  audio.end();
  audio.setPins(13,14,16,15,12); // BCLK, WS, DAC TX, MIC RX, MCLK
  bool ok=audio.begin(I2S_MODE_STD,RATE,I2S_DATA_BIT_WIDTH_16BIT,
                      I2S_SLOT_MODE_STEREO);
  Serial.printf("[AUDIO] STD full-duplex I2S 16-bit stereo 16kHz =%s\n",ok?"OK":"FAILED");
  return ok;
}
bool initSpeaker(){
  uint8_t r=0;if(!regRead(DAC,0,r))return false;
  bool ok=true;auto w=[&](uint8_t reg,uint8_t val){ok=regWrite(DAC,reg,val)&&ok;};
  w(0x00,0x1F);delay(20);w(0x00,0x00);w(0x00,0x80);w(0x01,0x3F);
  if(!regRead(DAC,0x06,r))return false;w(0x06,r&~(1u<<5));
  if(!regRead(DAC,0x02,r))return false;w(0x02,r&0x07);
  w(0x03,0x10);w(0x04,0x10);w(0x05,0x00);
  if(!regRead(DAC,0x06,r))return false;w(0x06,(r&0xE0)|0x03);
  if(!regRead(DAC,0x07,r))return false;w(0x07,r&0xC0);w(0x08,0xFF);
  if(!regRead(DAC,0x09,r))return false;w(0x09,(r&~0x1C)|0x0C);
  if(!regRead(DAC,0x0A,r))return false;w(0x0A,(r&~0x1C)|0x0C);
  w(0x0D,0x01);w(0x0E,0x02);w(0x12,0x00);w(0x13,0x10);
  w(0x1C,0x6A);w(0x37,0x08);w(0x31,0x00);w(0x32,0xAF);
  Serial.printf("[DAC] ES8311 setup=%s\n",ok?"OK":"ERROR");return ok;
}
void paint(uint8_t r,uint8_t g,uint8_t b){
  for(int i=0;i<NUM_LEDS;i++)ring.setPixelColor(i,ring.Color(r,g,b));ring.show();
}

// SAM LED effects: 7 WS2812 GPIO38. PC sends 'J' plus six bytes:
// mode (0 auto, 1 off, 2 solid, 3 breathe, 4 rainbow, 5 disco,
// 6 strobe, 7 chase, 8 pulse, 9 sparkle, 10 candle, 11 ocean,
// 12 party, 13 meteor), R, G, B, brightness 0-100, speed 0-100.
static uint8_t samLedMode=0,samLedR=20,samLedG=110,samLedB=255,samLedBright=75,samLedSpeed=45;
static inline uint8_t samClamp(int n){return (uint8_t)constrain(n,0,255);}
static void samPixel(int idx,int r,int g,int b){
  ring.setPixelColor(idx,ring.Color(samClamp(r),samClamp(g),samClamp(b)));
}
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
  if(samLedMode==6){
    uint32_t period=(uint32_t)(700-(samLedSpeed*2));
    if(period<500)period=500;
    if(t%period < period/2)paint(r,g,b);else paint(0,0,0);
    return;
  }
  if(samLedMode==10){
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
      int idx=((uint32_t)(cycles*2))%NUM_LEDS;
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
    }else{
      samPixel(i,r,g,b);
    }
  }
  ring.show();
}

void tickLeds(){
  if(samLedMode!=0){if(millis()-lastLed<45)return;lastLed=millis();samLeds();return;}
  ring.setBrightness(80);
  if(millis()-lastLed<45)return;
  lastLed=millis();
  uint8_t a=(uint8_t)(15+100*(0.5f-0.5f*cosf(6.2831853f*((millis()%2500)/2500.0f))));
  switch(phase){
    case IDLE: paint(0,a/2,a);break;
    case LISTEN: paint(a,0,a);break;
    case THINK: paint(a,a/2,0);break;
    case REPLY: paint(0,a,20);break;
    case ERROR_PHASE: paint(a,0,0);break;
  }
}
bool key2(){
  uint8_t v=0xFF;if(!regRead(EXP,0x01,v))return false;
  bool pressed=(lastKey&0x04)&&!(v&0x04);lastKey=v;
  static uint32_t last=0;
  if(pressed && millis()-last>250){last=millis();return true;}return false;
}
static inline uint32_t abs16(int16_t s){return s<0?(uint32_t)(-(int32_t)s):(uint32_t)s;}

// WAV: RIFF/PCM signed16 mono 16000 Hz. Sends mono samples to both DAC slots.
bool playReply(Stream& stream){
  uint8_t header[12]={0};
  if(stream.readBytes((char*)header,12)!=12||memcmp(header,"RIFF",4)||memcmp(header+8,"WAVE",4))return false;
  auto le16=[](const uint8_t*p)->uint16_t{return (uint16_t)p[0]|((uint16_t)p[1]<<8);};
  auto le32=[](const uint8_t*p)->uint32_t{return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);};
  bool fmt=false;uint16_t channels=0,bits=0,encoding=0;uint32_t hz=0,remaining=0;
  for(int i=0;i<16;i++){
    uint8_t ch[8];if(stream.readBytes((char*)ch,8)!=8)return false;
    uint32_t len=le32(ch+4),orig=len;
    if(len>2000000u)return false;
    if(memcmp(ch,"fmt ",4)==0){
      if(len<16 || len>256)return false;
      uint8_t desc[256];if(stream.readBytes((char*)desc,len)!=len)return false;
      encoding=le16(desc);channels=le16(desc+2);hz=le32(desc+4);bits=le16(desc+14);fmt=true;
    }else if(memcmp(ch,"data",4)==0){remaining=len;break;
    }else{
      uint8_t drop[128];while(len){size_t n=len>sizeof(drop)?sizeof(drop):len;
        if(stream.readBytes((char*)drop,n)!=n)return false;len-=n;}
    }
    if((orig&1) && stream.readBytes((char*)ch,1)!=1)return false;
  }
  if(!fmt || !remaining || channels!=1||bits!=16||hz!=RATE||encoding!=1)return false;
  uint8_t mono[1024];int16_t stereo[1024];
  amp(true);bool success=true;
  while(remaining){
    size_t n=remaining>sizeof(mono)?sizeof(mono):remaining;
    n&=~1u;if(n==0){success=false;break;}
    if(stream.readBytes((char*)mono,n)!=n){success=false;break;}
    const int16_t* src=(const int16_t*)mono;
    for(size_t i=0;i<n/2;i++){stereo[2*i]=scalePlayback(src[i]);stereo[2*i+1]=stereo[2*i];}
    if(txMutex && xSemaphoreTake(txMutex,pdMS_TO_TICKS(1500))==pdTRUE){
      size_t wrote=audio.write((const uint8_t*)stereo,n*2);
      xSemaphoreGive(txMutex);
      if(wrote!=n*2){success=false;break;}
    }else{success=false;break;}
    remaining-=n;tickLeds();
  }
  memset(stereo,0,sizeof(stereo));
  if(txMutex && xSemaphoreTake(txMutex,pdMS_TO_TICKS(1500))==pdTRUE){
    audio.write((const uint8_t*)stereo,sizeof(stereo));xSemaphoreGive(txMutex);
  }
  delay(60);if(!musicActive)amp(false);return success;
}
void fetchAndPlay(){
  phase=REPLY;
  Serial.println("[TTS] Downloading reply WAV from Windows...");
  HTTPClient http;String url="http://"+String(SAM_PC_IP)+":"+String(SAM_PC_PORT)+"/v1/reply";
  if(!http.begin(url)){phase=ERROR_PHASE;return;}
  http.setTimeout(15000);http.addHeader("X-Sam-Token",SAM_TOKEN);
  int status=http.GET();bool okay=false;
  if(status==200){
    {
      WiFiClient* s=http.getStreamPtr();s->setTimeout(15000);okay=playReply(*s);
    }
    if(!musicActive)amp(false);
    // Playback used the shared TX channel. RX stays initialized throughout.
    // Ignore buffered loopback audio while playback finishes.
    uint8_t flush[256];
    audio.setTimeout(40);
    for(int n=0;n<8;n++){if(audio.readBytes((char*)flush,sizeof(flush))!=sizeof(flush))break;}
  }
  Serial.printf("[TTS] HTTP=%d speaker=%s\n",status,okay?"OK":"FAIL");
  http.end();phase=(okay && audioReady)?IDLE:ERROR_PHASE;
  if(!okay){delay(800);phase=IDLE;}
}
void connectAudio(){
  if(WiFi.status()!=WL_CONNECTED || upstream.connected())return;
  if(millis()-lastConnection<3000)return;
  lastConnection=millis();
  if(!upstream.connect(SAM_PC_IP,SAM_STREAM_PORT,2500)){
    Serial.printf("[LAN] Can't connect to %s:%d\n",SAM_PC_IP,SAM_STREAM_PORT);return;
  }
  upstream.setNoDelay(true);upstream.setTimeout(1600);
  String introduction="SAMSTREAM1 "+String(SAM_TOKEN)+"\n";
  if(upstream.write((const uint8_t*)introduction.c_str(),introduction.length())!=introduction.length()){
    upstream.stop();return;
  }
  // Explicit version frame: lets the PC prove the current firmware was flashed.
  const uint8_t verLen=(uint8_t)strlen(FW_VER);
  upstream.write((const uint8_t*)"V",1);
  upstream.write(&verLen,1);
  upstream.write((const uint8_t*)FW_VER,verLen);
  Serial.printf("[LAN] Firmware %s; ES7210 16-bit standard I2S 16kHz stereo to %s:%d\n",FW_VER,SAM_PC_IP,SAM_STREAM_PORT);
  phase=IDLE;
}
void pushSamples(){
  if(!upstream.connected())return;
  audio.setTimeout(1500);
  const size_t n=audio.readBytes((char*)micStereo,sizeof(micStereo));
  if(n!=sizeof(micStereo)){
    Serial.printf("[I2S] Short read %u/%u\n",(unsigned)n,(unsigned)sizeof(micStereo));
    return;
  }
  for(unsigned frame=0;frame<FRAMES_PER_PACKET;frame++){
    for(unsigned ch=0;ch<2;ch++){
      const int16_t v=micStereo[frame*2+ch];
      uint32_t a=abs16(v);
      if(a>samplePeak)samplePeak=a;
      if(v)sampleNonzero++;
      sampleCount++;
      if(ch==0){const unsigned phase=frame&7u;samplePhaseCount[phase]++;
        if(v==0)sampleZeroPhases[phase]++;}
    }
  }
  const uint8_t hdr[3]={'A',(uint8_t)(FRAMES_PER_PACKET&255),(uint8_t)(FRAMES_PER_PACKET>>8)};
  if(upstream.write(hdr,3)!=3 ||
     upstream.write((const uint8_t*)micStereo,sizeof(micStereo))!=sizeof(micStereo)){
    Serial.println("[LAN] Stream send failed, reconnecting");upstream.stop();return;
  }
  transmittedFrames+=FRAMES_PER_PACKET;
}

void processCommands(){
  while(upstream.connected() && upstream.available()){
    char cmd=(char)upstream.read();
    if(cmd=='G'){
      uint8_t value=75;
      if(upstream.readBytes((char*)&value,1)==1){speakerVolume=value>100?100:value;
        Serial.printf("[VOLUME] output set to %u%%\n",speakerVolume);
      }
    }
    else if(cmd=='J'){
      uint8_t data[6]={0,0,0,0,0,0};
      if(upstream.readBytes((char*)data,6)==6 && data[0]<=13 && data[4]<=100 && data[5]<=100){
        samLedMode=data[0];samLedR=data[1];samLedG=data[2];samLedB=data[3];
        samLedBright=data[4];samLedSpeed=data[5];
        Serial.printf("[LED] mode=%u brightness=%u speed=%u\n",samLedMode,samLedBright,samLedSpeed);
      }
    }
    else if(cmd=='I')phase=IDLE;
    else if(cmd=='L')phase=LISTEN;
    else if(cmd=='T')phase=THINK;
    else if(cmd=='P'){fetchAndPlay();if(upstream.connected())upstream.write((const uint8_t*)"D",1);phase=IDLE;}
    else if(cmd=='E')phase=ERROR_PHASE;
    else if(cmd=='O')Serial.println("[LAN] PC authorized audio stream");
  }
}
void setup(){
  Serial.begin(115200);delay(450);
  Serial.printf("\n%s / PC-WAKE / stock ESPHome 16-bit standard I2S driver\n",FW_VER);
  ring.begin();ring.setBrightness(80);paint(0,15,35);
  Wire.begin(11,10,100000);expPin(8,false);  // amp OFF when idle
  uint8_t cfg=0;if(regRead(EXP,0x07,cfg))regWrite(EXP,0x07,(uint8_t)(cfg|0x0E));
  bool m=initMic();bool d=initSpeaker();
  txMutex=xSemaphoreCreateMutex();
  // This board's SD card CS line must be HIGH in 1-bit SDMMC mode.
  const bool sdCsOk=expPin(3,true);
  if(!sdCsOk)Serial.println("[SD] WARNING: EXIO3 CS not set");
  SD_MMC.setPins(40,42,41);
  sdReady=sdCsOk && SD_MMC.begin("/sdcard",true,false,SDMMC_FREQ_DEFAULT,5);
  if(sdReady){findSongs("/",0);Serial.printf("[SD] mounted, %u MP3 tracks found\n",(unsigned)songs.size());}
  else Serial.println("[SD] card not mounted. SAM voice still operates normally.");
  audioReady=captureMode();
  Serial.printf("[START] mics=%s dac=%s I2S=%s\n",m?"OK":"BAD",d?"OK":"BAD",audioReady?"OK":"BAD");
  if(!(m&&audioReady)){phase=ERROR_PHASE;return;}
  WiFi.mode(WIFI_STA);WiFi.setSleep(false);WiFi.begin(SAM_WIFI_SSID,SAM_WIFI_PASS);
  Serial.println("[START] PC continuously detects Hey Sam. K2 is backup. Blue=idle/purple=listen/amber=think/green=speech.");
}
void loop(){
  tickLeds();
  if(!audioReady){delay(100);return;}
  if(WiFi.status()!=WL_CONNECTED){
    static uint32_t lastTry=0;
    if(millis()-lastTry>12000){lastTry=millis();WiFi.reconnect();Serial.println("[WIFI] Reconnecting...");}
    delay(70);return;
  }
  static bool serversStarted=false;
  if(!serversStarted){
    sdHttp.begin();musicStream.begin();
    xTaskCreatePinnedToCore(sdTask,"sam_sd_http",8192,nullptr,1,nullptr,0);
    xTaskCreatePinnedToCore(musicTask,"sam_music_pcm",8192,nullptr,2,nullptr,0);
    serversStarted=true;
    Serial.printf("[SD] HTTP :%u and music stream :%u ready\n",SD_HTTP_PORT,MUSIC_STREAM_PORT);
  }
  connectAudio();
  if(upstream.connected()){
    processCommands();
    if(key2()){
      Serial.println("[K2] Wake request sent to PC");
      if(upstream.write((const uint8_t*)"B",1)!=1)upstream.stop();
    }
    // Normal use requires no button. K2 remains optional diagnostic only.
    pushSamples();
    processCommands();
  }
  if(millis()-lastLog>LOG_INTERVAL){
    lastLog=millis();
    Serial.printf("[STAT] wifi=%s stream=%s audio_frames=%llu peak=%lu nonzero=%lu/%lu\n",
      WiFi.status()==WL_CONNECTED?"OK":"OFF",upstream.connected()?"OK":"OFF",
      (unsigned long long)transmittedFrames,(unsigned long)samplePeak,
      (unsigned long)sampleNonzero,(unsigned long)sampleCount);
    Serial.printf("[I2S] ZERO PHASE 0..7 left channel counts:");
    for(int i=0;i<8;i++){Serial.printf(" %lu/%lu",(unsigned long)sampleZeroPhases[i],(unsigned long)samplePhaseCount[i]);
      sampleZeroPhases[i]=0;samplePhaseCount[i]=0;}
    Serial.println();
    samplePeak=0;sampleNonzero=0;sampleCount=0;
  }
  delay(1);
}
