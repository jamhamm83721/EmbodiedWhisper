#include "sdkconfig.h"
#include "lwip_demo.h"

#define IP_ADDR CONFIG_EW_SERVER_IPV4

#define LWIP_DEMO_RX_BUFSIZE            100                        /* 最大接收数据长度 */
#define LWIP_DEMO_PORT                  CONFIG_EW_SERVER_PORT                       /* 连接的本地端口号 */
#define LWIP_SEND_THREAD_PRIO           (tskIDLE_PRIORITY+3)    /* 发送数据线程优先级 */
/* camera一次命令传输的图像张数 */
int16_t pic_num;
/* 接收数据缓冲区 */
uint8_t g_lwip_demo_recvbuf[LWIP_DEMO_RX_BUFSIZE];
/* 发送数据内容 */
uint8_t g_lwip_demo_sendbuf[] = "EmbodiedWhisper\r\n";
/* 数据发送标志位 */
uint8_t g_lwip_send_flag;
int g_sock = -1;
int g_lwip_connect_state = 0;
static void lwip_send_thread(void *arg);
static const char *TAG = "scan";

static int socket_send_all(int sock, const void *data, size_t len)
{
    const uint8_t *ptr = (const uint8_t *)data;
    size_t sent_total = 0;

    while (sent_total < len)
    {
        int sent = send(sock, ptr + sent_total, len - sent_total, 0);
        if (sent <= 0)
        {
            return -1;
        }
        sent_total += sent;
    }

    return 0;
}


void lwip_data_send(void)
{
    xTaskCreate(lwip_send_thread, "lwip_send_thread", 4096, NULL, LWIP_SEND_THREAD_PRIO, NULL);
}

void lwip_demo(void)
{
    struct sockaddr_in atk_client_addr;
    err_t err;
    int recv_data_len;
    char *tbuf;

    lwip_data_send();
    while(1)
    {
sock_start:
        g_lwip_connect_state = 0;
        atk_client_addr.sin_family = AF_INET;                   /* 表示IPv4网络协议 */
        atk_client_addr.sin_port = htons(LWIP_DEMO_PORT);       /* 端口号 */
        atk_client_addr.sin_addr.s_addr = inet_addr(IP_ADDR);   /* 远程IP地址 */
        g_sock = socket(AF_INET, SOCK_STREAM, 0);                /* 可靠数据流交付服务，即TCP协议 */
        int tcp_nodelay = 1;
        setsockopt(g_sock, IPPROTO_TCP, TCP_NODELAY, &tcp_nodelay, sizeof(tcp_nodelay));
        memset(&(atk_client_addr.sin_zero), 0, sizeof(atk_client_addr.sin_zero));

        tbuf = malloc(200);                                     /* 申请内存 */
        printf("Port:%d\n",LWIP_DEMO_PORT);
        err = connect(g_sock, (struct sockaddr *)&atk_client_addr, sizeof(struct sockaddr));
        if (err == -1)
        {
            printf("State:Disconnect\n");
            ESP_LOGI(TAG,"State:Disconnect");
            closesocket(g_sock);
            g_sock = -1;
            free(tbuf);
            vTaskDelay(10);
            goto sock_start;
        }
        printf("State:Connection Successful\n");
        ESP_LOGI(TAG,"State:Connection Successful");
        g_lwip_connect_state = 1;                               //TCP连接成功后，图像数据发送标志位置为真
        while(1)                                                //等待服务器消息
        {
            recv_data_len = recv(g_sock,g_lwip_demo_recvbuf,
                                 LWIP_DEMO_RX_BUFSIZE,0);

            if (recv_data_len <= 0 )
            {
                closesocket(g_sock);
                g_sock = -1;
                printf("State:Disconnect\n");
                ESP_LOGI(TAG,"State:Disconnect");
                free(tbuf);
                goto sock_start;
            }
            //有数据接收时才会到这里；无数据时阻塞等待recv，接收错误时重新连接
            // esp_wifi_set_ps(WIFI_PS_NONE);                          //Wi-Fi工作在全速状态下
            // printf("wifi full speed\n");
            // pic_num = 150;
            printf("recevice message:%s\r\n",g_lwip_demo_recvbuf);
            vTaskDelay(10);
        }

    }
}

void lwip_send_thread(void *pvParameters)
{
    pvParameters = pvParameters;
    printf("lwip_send_thread\r\n");
    camera_fb_t *camera_frame = NULL;
    while(1)
    {
        if(g_lwip_connect_state == 1)
        // if(g_lwip_connect_state == 1 && pic_num > 0)
        {
            camera_frame = esp_camera_fb_get();
            if (camera_frame == NULL)
            {
                vTaskDelay(10);
                continue;
            }

            uint32_t len = (uint32_t)camera_frame->len;
            if (socket_send_all(g_sock, &len, sizeof(len)) != 0 ||
                socket_send_all(g_sock, camera_frame->buf, camera_frame->len) != 0)
            {
                printf("send image failed\n");
                closesocket(g_sock);
                g_sock = -1;
                g_lwip_connect_state = 0;
            }
            esp_camera_fb_return(camera_frame);
            // pic_num--;
        }
        // else if(pic_num == 0)
        // {
        //     printf("wifi power save module\n");
        //     esp_wifi_set_ps(WIFI_PS_MAX_MODEM);
        //     pic_num = -1;
        // }
        vTaskDelay(1);
    }


    // err_t err;
    // while (1)
    // {
    //     while (1)
    //     {
    //         if(((g_lwip_send_flag & LWIP_SEND_DATA) == LWIP_SEND_DATA) && (g_lwip_connect_state == 1)) /* 有数据要发送 */
    //         {
    //             err = write(g_sock, g_lwip_demo_sendbuf, sizeof(g_lwip_demo_sendbuf));

    //             if (err < 0)
    //             {
    //                 break;
    //             }

    //             g_lwip_send_flag &= ~LWIP_SEND_DATA;
    //         }

    //         vTaskDelay(10);
    //     }

    //     closesocket(g_sock);
    // }
}
