#include <Wire.h>
#include "Adafruit_VL53L0X.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

Adafruit_VL53L0X lox = Adafruit_VL53L0X();

// Height of sensor above the floor in mm
const int SENSOR_HEIGHT_MM = 2200;

// Sensor range: 30–1000mm (standard mode)
const int MIN_RAW_DISTANCE_MM = 100;
const int MAX_RAW_DISTANCE_MM = 1000;

// Number of consecutive detections required before sending BLE reading
const int REQUIRED_CONSECUTIVE_DETECTIONS = 3;

// Delay between each reading in milliseconds
const int READING_INTERVAL_MS = 1000;

#define SERVICE_UUID        "6E400001-B5B4-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID "6E400003-B5B4-F393-E0A9-E50E24DCCA9E"

BLEServer* pServer = NULL;
BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) {
    deviceConnected = true;
    Serial.println("Client connected");
  }
  void onDisconnect(BLEServer* pServer) {
    deviceConnected = false;
    Serial.println("Client disconnected");
    pServer->startAdvertising();
  }
};

void printHeight(int heightMM) {
  int metres = heightMM / 1000;
  int cm = (heightMM % 1000) / 10;

  float totalInches = heightMM / 25.4;
  int feet = (int)(totalInches / 12);
  int inches = (int)(totalInches) % 12;

  Serial.print("Height: ");
  Serial.print(metres);
  Serial.print("m ");
  Serial.print(cm);
  Serial.print("cm  |  ");
  Serial.print(feet);
  Serial.print("ft ");
  Serial.print(inches);
  Serial.println("in");
}

void setup() {
  Serial.begin(115200);
  delay(READING_INTERVAL_MS);
  Wire.begin(21, 22);

  if (!lox.begin()) {
    Serial.println("Failed to find VL53L0X sensor!");
    while (1);
  }

  BLEDevice::init("ESP32-HeightSensor");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());

  BLEService* pService = pServer->createService(SERVICE_UUID);
  pCharacteristic = pService->createCharacteristic(
    CHARACTERISTIC_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  pCharacteristic->addDescriptor(new BLE2902());
  pService->start();

  BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->start();

  Serial.println("Ready.");
}

void loop() {
  static int consecutiveDetections = 0;
  static long heightSum = 0;

  VL53L0X_RangingMeasurementData_t measure;
  lox.rangingTest(&measure, false);

  int raw = measure.RangeMilliMeter;
  Serial.print("Raw distance: ");
  Serial.print(raw);
  Serial.println(" mm");

  bool personDetected = (measure.RangeStatus != 4) &&
                        (raw >= MIN_RAW_DISTANCE_MM) &&
                        (raw <= MAX_RAW_DISTANCE_MM);

  Serial.print("Person detected: ");
  Serial.println(personDetected ? "true" : "false");

  if (personDetected) {
    int personHeight = SENSOR_HEIGHT_MM - raw;
    printHeight(personHeight);
    consecutiveDetections++;
    heightSum += personHeight;
    Serial.print("Consecutive detections: ");
    Serial.println(consecutiveDetections);

    if (consecutiveDetections >= REQUIRED_CONSECUTIVE_DETECTIONS) {
      int avgHeight = heightSum / consecutiveDetections;
      Serial.print(">> Sending over BLE: ");
      Serial.print(avgHeight);
      Serial.println(" mm");

      if (deviceConnected) {
        String msg = String(avgHeight) + "\n";
        pCharacteristic->setValue(msg.c_str());
        pCharacteristic->notify();
        Serial.println(">> Sent. Waiting 15s before reset.");
      } else {
        Serial.println(">> BLE not connected.");
      }

      delay(15000);
      consecutiveDetections = 0;
      heightSum = 0;
    }
  } else {
    if (consecutiveDetections > 0) {
      Serial.println("Detection broken — resetting count");
    }
    consecutiveDetections = 0;
    heightSum = 0;
  }

  delay(READING_INTERVAL_MS);
}
