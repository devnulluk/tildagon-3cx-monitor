#pragma once
#include <NimBLEDevice.h>
#include <Preferences.h>
#include <mbedtls/aes.h>
#include "presence_policy.h"
#include "nimble/nimble/host/include/host/ble_store.h"
namespace spaceport {
class PhonePresence {
 PresencePolicy policy; uint8_t irk[16]={}; ble_addr_t identity={};
 portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;
 NimBLEServer* server=nullptr; uint32_t until=0,lastPoll=0; volatile uint16_t connection=BLE_HS_CONN_HANDLE_NONE;
 class ServerCallbacks:public NimBLEServerCallbacks {
  PhonePresence& owner;
 public: explicit ServerCallbacks(PhonePresence& o):owner(o){}
  void onConnect(NimBLEServer* s,ble_gap_conn_desc* d) override {if(!owner.pairing()){s->disconnect(d->conn_handle);return;}owner.connection=d->conn_handle;NimBLEDevice::startSecurity(d->conn_handle);}
  void onDisconnect(NimBLEServer*,ble_gap_conn_desc*) override {owner.connection=BLE_HS_CONN_HANDLE_NONE;}
 } serverCallbacks{*this};
 class ScanCallbacks:public NimBLEAdvertisedDeviceCallbacks {
  PhonePresence& owner;
 public:explicit ScanCallbacks(PhonePresence& o):owner(o){}
  void onResult(NimBLEAdvertisedDevice* d) override {owner.observe(d);}
 } scanCallbacks{*this};
 bool matches(const NimBLEAddress& address) {
  const uint8_t* a=address.getNative();
  if((address.getType()&1)==(identity.type&1)&&!memcmp(a,identity.val,6))return true;
  if(!(address.getType()&1)||(a[5]&0xc0)!=0x40)return false;
  // Bluetooth ah: bond-store keys are little endian; AES takes big endian.
  uint8_t key[16],block[16]={},out[16];for(int i=0;i<16;i++)key[i]=irk[15-i];
  block[13]=a[5];block[14]=a[4];block[15]=a[3];
  mbedtls_aes_context aes;mbedtls_aes_init(&aes);
  int rc=mbedtls_aes_setkey_enc(&aes,key,128);if(!rc)rc=mbedtls_aes_crypt_ecb(&aes,MBEDTLS_AES_ENCRYPT,block,out);mbedtls_aes_free(&aes);
  return !rc&&out[15]==a[0]&&out[14]==a[1]&&out[13]==a[2];
 }
 void observe(NimBLEAdvertisedDevice* d) {portENTER_CRITICAL(&mux);bool enrolled=policy.enrolled;portEXIT_CRITICAL(&mux);if(!enrolled||!matches(d->getAddress()))return;portENTER_CRITICAL(&mux);policy.observe(d->getRSSI(),millis());portEXIT_CRITICAL(&mux);}
 void save() {Preferences p;p.begin("presence",false);p.putBool("enabled",policy.enabled);p.putInt("threshold",policy.threshold);p.putUInt("grace",policy.grace);p.end();}
 public:
 void begin() {
  Preferences p;p.begin("presence",true);policy.enabled=p.getBool("enabled",false);policy.threshold=constrain(p.getInt("threshold",-72),-95,-35);policy.grace=constrain(p.getUInt("grace",60000),15000u,300000u);
  policy.enrolled=p.getBytesLength("irk")==16&&p.getBytesLength("identity")==sizeof(identity);if(policy.enrolled){p.getBytes("irk",irk,16);p.getBytes("identity",&identity,sizeof(identity));}p.end();
  NimBLEDevice::init("Spaceport Presence");NimBLEDevice::setSecurityAuth(true,false,true);NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);NimBLEDevice::setSecurityInitKey(BLE_SM_PAIR_KEY_DIST_ENC|BLE_SM_PAIR_KEY_DIST_ID);NimBLEDevice::setSecurityRespKey(BLE_SM_PAIR_KEY_DIST_ENC|BLE_SM_PAIR_KEY_DIST_ID);
  server=NimBLEDevice::createServer();server->setCallbacks(&serverCallbacks,false);server->advertiseOnDisconnect(false);
  auto service=server->createService("180D");auto measurement=service->createCharacteristic("2A37",NIMBLE_PROPERTY::READ|NIMBLE_PROPERTY::READ_ENC|NIMBLE_PROPERTY::NOTIFY);uint8_t empty[]={0,0};measurement->setValue(empty,2);service->start();
  server->start(); // Commit GATT before scanning; NimBLE cannot reset GATT during GAP discovery.
  auto adv=NimBLEDevice::getAdvertising();adv->addServiceUUID("180D");adv->setName("Spaceport Presence");adv->setScanResponse(true);
  auto scan=NimBLEDevice::getScan();scan->setAdvertisedDeviceCallbacks(&scanCallbacks,true);scan->setActiveScan(false);scan->setInterval(300);scan->setWindow(40);scan->setMaxResults(0);scan->start(0,static_cast<void(*)(NimBLEScanResults)>(nullptr));
 }
 PresencePolicy status(){portENTER_CRITICAL(&mux);auto result=policy;portEXIT_CRITICAL(&mux);return result;}
 bool allows(){return status().allows(millis());}
 bool pairing()const{return until&&int32_t(until-millis())>0;}
 void enable(bool value){portENTER_CRITICAL(&mux);policy.enabled=value;portEXIT_CRITICAL(&mux);save();}
 void threshold(int value){portENTER_CRITICAL(&mux);policy.threshold=constrain(value,-95,-35);policy.seen=false;portEXIT_CRITICAL(&mux);save();}
 void timeout(int seconds){portENTER_CRITICAL(&mux);policy.grace=constrain(seconds,15,300)*1000;portEXIT_CRITICAL(&mux);save();}
 void pair(){if(status().enrolled)return;enable(true);until=millis()+120000;NimBLEDevice::getAdvertising()->start();}
 void forget(){until=0;NimBLEDevice::getAdvertising()->stop();if(connection!=BLE_HS_CONN_HANDLE_NONE)server->disconnect(connection);NimBLEDevice::getScan()->stop();portENTER_CRITICAL(&mux);policy.enrolled=false;policy.seen=false;portEXIT_CRITICAL(&mux);memset(irk,0,16);Preferences p;p.begin("presence",false);p.remove("irk");p.remove("identity");p.end();NimBLEDevice::deleteAllBonds();NimBLEDevice::getScan()->start(0,static_cast<void(*)(NimBLEScanResults)>(nullptr));}
 void tick(){
  if(until&&!pairing()){until=0;NimBLEDevice::getAdvertising()->stop();if(connection!=BLE_HS_CONN_HANDLE_NONE)server->disconnect(connection);}
  if(!pairing()||connection==BLE_HS_CONN_HANDLE_NONE||millis()-lastPoll<500)return;lastPoll=millis();
  ble_gap_conn_desc d{};if(ble_gap_conn_find(connection,&d)||!d.sec_state.encrypted)return;
  ble_store_key_sec key{};key.peer_addr=d.peer_id_addr;ble_store_value_sec bond{};
  if(ble_store_read_peer_sec(&key,&bond)||!bond.irk_present)return;
  NimBLEDevice::getScan()->stop();memcpy(irk,bond.irk,16);identity=d.peer_id_addr;
  Preferences p;p.begin("presence",false);p.putBytes("irk",irk,16);p.putBytes("identity",&identity,sizeof(identity));p.end();
  portENTER_CRITICAL(&mux);policy.enrolled=true;policy.seen=false;portEXIT_CRITICAL(&mux);
  until=0;NimBLEDevice::getAdvertising()->stop();server->disconnect(connection);NimBLEDevice::getScan()->start(0,static_cast<void(*)(NimBLEScanResults)>(nullptr));
 }
};
}
