

#ifndef __LWIP_H_
#define __LWIP_H_

#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include "lwip/sockets.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "camera.h"
#include "esp_event.h"
#include "esp_log.h"

#define LWIP_SEND_DATA              0X80    /* 定义有数据发送 */
extern uint8_t g_lwip_send_flag;            /* 数据发送标志位 */

void lwip_demo(void);

#endif
