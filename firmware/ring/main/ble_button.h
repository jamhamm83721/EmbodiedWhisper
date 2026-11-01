#ifndef __BLE_BUTTON_H__
#define __BLE_BUTTON_H__

#include "esp_err.h"
#include "button.h"

#define BLE_BUTTON_DEVICE_NAME "ESP32S3-Button"
#define BLE_BUTTON_SERVICE_UUID "12345678-1234-5678-1234-56789abcdef0"
#define BLE_BUTTON_CHAR_UUID "12345678-1234-5678-1234-56789abcdef1"

esp_err_t ble_button_init(void);
void ble_button_publish_event(button_event_t event);

#endif
