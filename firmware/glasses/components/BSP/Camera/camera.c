#include "camera.h"


static camera_config_t camera_config = {
    .pin_pwdn = CAM_PIN_PWDN,
    .pin_reset = CAM_PIN_RESET,
    .pin_xclk = CAM_PIN_XCLK,
    .pin_sccb_sda = CAM_PIN_SIOD,
    .pin_sccb_scl = CAM_PIN_SIOC,
    .pin_d7 = CAM_PIN_D7,
    .pin_d6 = CAM_PIN_D6,
    .pin_d5 = CAM_PIN_D5,
    .pin_d4 = CAM_PIN_D4,
    .pin_d3 = CAM_PIN_D3,
    .pin_d2 = CAM_PIN_D2,
    .pin_d1 = CAM_PIN_D1,
    .pin_d0 = CAM_PIN_D0,
    .pin_vsync = CAM_PIN_VSYNC,
    .pin_href = CAM_PIN_HREF,
    .pin_pclk = CAM_PIN_PCLK,
    /* 输出图像配置 */
    .xclk_freq_hz = 24*1000*1000,
    .ledc_timer = LEDC_TIMER_0,
    .ledc_channel = LEDC_CHANNEL_0,
    .fb_location = CAMERA_FB_IN_PSRAM,
    .pixel_format = PIXFORMAT_JPEG,                 /* 图像输出模式 */
    .frame_size = FRAMESIZE_240X240,                /* 图像输出大小 */
    .jpeg_quality = 15,                             /* 0-63，对于OV系列摄像头，数值越小质量越高 */
    .fb_count = 2,                                  /* 图片缓存区为2时，读取速度约为单缓存的两倍 */
    .grab_mode = CAMERA_GRAB_LATEST,

};


uint8_t camera_init(void)
{
    esp_err_t err = ESP_OK;
    err = esp_camera_init(&camera_config);
    if(err != ESP_OK)
    {
        printf("camera init failed!!\n");
        return 1;
    }
    sensor_t *s = esp_camera_sensor_get();
    printf("camera:%x\n",s->id.PID);
    if(s->id.PID == OV3660_PID)
    {
        s->set_vflip(s, 1);
        s->set_brightness(s,  1);
        s->set_saturation(s, -2);
    }
    else if(s->id.PID == OV5640_PID)
    {
        s->set_vflip(s, 1);
    }
    return err;
}
