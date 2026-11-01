#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "button.h"
#include "ble_button.h"

/* Release integration entry point; this is not the archived experiment entry point. */
static void on_button_event(button_event_t event)
{
    ble_button_publish_event(event);
}

void app_main(void)
{
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(result);
    ESP_ERROR_CHECK(button_init());
    ESP_ERROR_CHECK(ble_button_init());
    button_start_task(on_button_event);
    vTaskDelete(NULL);
}
