// skyguard_edge.ino
// Arduino sketch using C rule_gate and tiny_tree
// BME280 (T/RH/P) + battery ADC + MQTT publish

#include <Wire.h>
// #include <Adafruit_BME280.h>
// #include <PubSubClient.h>

extern "C" {
    #include "../../c/rule_gate.h"
    #include "../../c/tiny_tree.h"
}

#define BATT_PIN 34
#define REPORT_INTERVAL_CALM_MS (15 * 60 * 1000)
#define REPORT_INTERVAL_ACTIVE_MS (60 * 1000)

void setup() {
    Serial.begin(115200);
    // Wire.begin();
    // bme.begin();
}

void loop() {
    // Read sensor (mock)
    float t = 25.0;
    float rh = 50.0;
    float p = 1010.0;
    float batt = analogRead(BATT_PIN) * (3.3 / 4095.0) * 2.0;

    // Build row
    rg_row_t row;
    row.T = t; row.has_T = true;
    row.Td = t - ((100 - rh) / 5.0); row.has_Td = true;
    row.RH = rh; row.has_RH = true;
    row.P = p; row.has_P = true;
    row.cadence_min = 15;
    row.is_metar_speci = false;
    row.ts_utc = 1716300000; // mock ts

    // rg_check(&row, 1);
    
    // float features[5] = {0, 0, 0, 0, 0};
    // int is_anomaly = tree_predict(features);

    delay(1000);
}
