#include <esp_now.h>
#include <WiFi.h>

// 👉 ESP2 MAC
uint8_t peerAddress[] = {0xEC, 0xE3, 0x34, 0x19, 0x75, 0x8C};

typedef struct struct_message {
  char msg[32];
} struct_message;

struct_message sendData;
struct_message recvData;

esp_now_peer_info_t peerInfo;

// استقبال
void OnDataRecv(const uint8_t * mac, const uint8_t *incomingData, int len) {
  memcpy(&recvData, incomingData, sizeof(recvData));

  Serial.print("ESP2 says: ");
  Serial.println(recvData.msg);
}

// حالة الإرسال
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  Serial.print("Send Status: ");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW Init Failed");
    return;
  }

  esp_now_register_send_cb(OnDataSent);
  esp_now_register_recv_cb(OnDataRecv);

  memcpy(peerInfo.peer_addr, peerAddress, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add peer");
    return;
  }
}

void loop() {
  strcpy(sendData.msg, "Hi from ESP1");

  esp_now_send(peerAddress, (uint8_t *) &sendData, sizeof(sendData));

  delay(3000);
}