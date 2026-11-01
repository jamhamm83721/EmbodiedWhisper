#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"


/*BSP*/
#include "led.h"
#include "usart.h"
#include "key.h"
#include "iic.h"
#include "wifi.h"
#include "esp_wifi.h"
#include "lwip_demo.h"
#include "camera.h"

#include <stdio.h>

#include "mdns.h"
#include "esp_system.h"
#include "esp_chip_info.h"
#include "esp_psram.h"
#include "esp_flash.h"
#include "nvs_flash.h"


i2c_obj_t i2c0_master;

#define HOSTNAME "my-esp32"

/* FreeRTOS配置 */
#define LED_TASK_PRIO       10          //任务优先级
#define LED_STK_SIZE        2048        //任务堆栈大小
TaskHandle_t  LEDTask_Handler;          //任务句柄
void led_task(void *pvParameters);      //任务函数

#define KEY_TASK_PRIO       11
#define KEY_STK_SIZE        2048
TaskHandle_t  KEYTask_Handler;
void key_task(void *pvParameters);





// static portMUX_TYPE my_spinlock = portMUX_INITIALIZER_UNLOCKED;





/**
 * @brief       程序入口
 * @param       无
 * @retval      无
 */
void app_main(void)
{

    esp_err_t ret;
    ret = nvs_flash_init();
    if(ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    // key_init();
    // i2c0_master = iic_init(I2C_NUM_0);  /* 初始化IIC0 */
    printf("TCP\n");
    wifi_sta_init();        //Wi-Fi是芯片发热的主要来源
    esp_wifi_set_ps(WIFI_PS_NONE);
    printf("wifi power save off\n");


    // esp_err_t err = mdns_init();
    // if (err != ESP_OK) {
    //     printf("mDNS Init Failed: %d\n", err);
    // } else {
    //     // 3. 服务启动成功后，再设置主机名
    //     mdns_hostname_set(HOSTNAME);
    //     printf("mDNS Init Success! Hostname: %s.local\n", HOSTNAME);
    // }


    // esp_wifi_set_ps(WIFI_PS_MAX_MODEM);     // Wi-Fi进入省电状态
    while(camera_init())
    {
        vTaskDelay(500);
    }
    printf("camera init succeed!\n");
    /* 临界区，保护代码不被其他任务中断 */
    // taskENTER_CRITICAL(&my_spinlock);
    // xTaskCreate((TaskFunction_t )key_task,
    //             (const char *   )"key_task",
    //             (uint16_t       )KEY_STK_SIZE,
    //             (void *         )NULL,
    //             (UBaseType_t    )KEY_TASK_PRIO,
    //             (TaskHandle_t * )&KEYTask_Handler);

    // xTaskCreate((TaskFunction_t )led_task,
    //             (const char *   )"led_task",
    //             (uint16_t       )LED_STK_SIZE,
    //             (void *         )NULL,
    //             (UBaseType_t    )LED_TASK_PRIO,
    //             (TaskHandle_t * )&LEDTask_Handler);

    // taskEXIT_CRITICAL(&my_spinlock);
    // send_jpeg_task();
    lwip_demo();
}


void key_task(void *pvParameters)
{
    pvParameters = pvParameters;
    uint8_t key;
    while(1)
    {
        key = key_scan(0);
        if(key == BOOT_PRES)
        {
            g_lwip_send_flag |= LWIP_SEND_DATA;      /* 标记LWIP有数据要发送 */
        }
        vTaskDelay(10);
    }
}


void led_task(void *pvParameters)
{
    pvParameters = pvParameters;

    while (1)
    {
        LED_TOGGLE();
        vTaskDelay(500);
    }
}
