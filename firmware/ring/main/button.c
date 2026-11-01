#include <stdbool.h>
#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "button.h"

static const char *TAG = "button";

static button_callback_t s_button_callback = NULL;
static volatile bool s_button_pressed = false;

static inline int button_read_level(void)
{
    return gpio_get_level(BUTTON_GPIO);
}

static inline bool button_level_is_pressed(int level)
{
    return level == BUTTON_ACTIVE_LEVEL;
}

esp_err_t button_init(void)
{
    gpio_config_t io_conf = {
        .pin_bit_mask = 1ULL << BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = BUTTON_ACTIVE_LEVEL == 0 ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = BUTTON_ACTIVE_LEVEL == 0 ? GPIO_PULLDOWN_DISABLE : GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "button gpio init failed");
        return ret;
    }

    s_button_pressed = button_level_is_pressed(button_read_level());
    ESP_LOGI(TAG, "button init on GPIO%d, active level=%d", BUTTON_GPIO, BUTTON_ACTIVE_LEVEL);
    return ESP_OK;
}

bool button_is_pressed(void)
{
    return s_button_pressed;
}

static void button_notify(button_event_t event)
{
    if (s_button_callback != NULL) {
        s_button_callback(event);
    }
}

static void button_task(void *arg)
{
    int last_raw_level = button_read_level();
    int stable_level = last_raw_level;
    TickType_t last_change_tick = xTaskGetTickCount();
    TickType_t press_tick = 0;
    bool long_press_reported = false;

    (void)arg;
    s_button_pressed = button_level_is_pressed(stable_level);

    while (1) {
        const TickType_t now = xTaskGetTickCount();
        const int raw_level = button_read_level();

        if (raw_level != last_raw_level) {
            last_raw_level = raw_level;
            last_change_tick = now;
        }

        if ((now - last_change_tick) >= pdMS_TO_TICKS(BUTTON_DEBOUNCE_MS) &&
            stable_level != raw_level) {
            stable_level = raw_level;
            s_button_pressed = button_level_is_pressed(stable_level);

            if (s_button_pressed) {
                press_tick = now;
                long_press_reported = false;
                button_notify(BUTTON_EVENT_PRESSED);
            } else {
                button_notify(BUTTON_EVENT_RELEASED);
                if (!long_press_reported) {
                    button_notify(BUTTON_EVENT_CLICKED);
                }
            }
        }

        if (s_button_pressed &&
            !long_press_reported &&
            (now - press_tick) >= pdMS_TO_TICKS(BUTTON_LONG_PRESS_MS)) {
            long_press_reported = true;
            button_notify(BUTTON_EVENT_LONG_PRESSED);
        }

        vTaskDelay(pdMS_TO_TICKS(BUTTON_SCAN_PERIOD_MS));
    }
}

void button_start_task(button_callback_t callback)
{
    s_button_callback = callback;
    xTaskCreate(button_task, "button_task", 2048, NULL, 4, NULL);
}
