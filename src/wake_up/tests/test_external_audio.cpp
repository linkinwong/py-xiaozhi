#include "../include/wake_up/wake_up_detector.h"
#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>
#include <csignal>
#include <alsa/asoundlib.h>

std::atomic<bool> g_wake_up_detected(false);
std::atomic<bool> g_running(true);

// 信号处理函数，用于捕获Ctrl+C
void signalHandler(int signum) {
    std::cout << "中断信号 (" << signum << ") 已收到，即将退出...\n";
    g_running = false;
}

void onWakeUp(const std::string& keyword, int confidence) {
    std::cout << "\n===== 唤醒词检测到 =====\n";
    std::cout << "关键词: " << keyword << "\n";
    std::cout << "置信度: " << confidence << "\n";
    std::cout << "========================\n\n";
    g_wake_up_detected = true;
    
    // 在实际应用中，这里可以触发其他操作，比如启动语音识别
}

// 音频捕获线程
void captureAudio(WakeUpDetector& detector) {
    // ALSA参数
    int err;
    snd_pcm_t *capture_handle;
    snd_pcm_hw_params_t *hw_params;
    const char *device = "default";
    unsigned int sample_rate = 16000;
    int channels = 1;
    int format = SND_PCM_FORMAT_S16_LE;
    
    // 打开音频设备
    if ((err = snd_pcm_open(&capture_handle, device, SND_PCM_STREAM_CAPTURE, 0)) < 0) {
        std::cerr << "无法打开音频设备: " << snd_strerror(err) << "\n";
        return;
    }
    
    // 分配hw_params结构
    if ((err = snd_pcm_hw_params_malloc(&hw_params)) < 0) {
        std::cerr << "无法分配硬件参数结构: " << snd_strerror(err) << "\n";
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 初始化hw_params
    if ((err = snd_pcm_hw_params_any(capture_handle, hw_params)) < 0) {
        std::cerr << "无法初始化硬件参数: " << snd_strerror(err) << "\n";
        snd_pcm_hw_params_free(hw_params);
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 设置访问类型
    if ((err = snd_pcm_hw_params_set_access(capture_handle, hw_params, SND_PCM_ACCESS_RW_INTERLEAVED)) < 0) {
        std::cerr << "无法设置访问类型: " << snd_strerror(err) << "\n";
        snd_pcm_hw_params_free(hw_params);
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 设置采样格式
    if ((err = snd_pcm_hw_params_set_format(capture_handle, hw_params, (snd_pcm_format_t)format)) < 0) {
        std::cerr << "无法设置采样格式: " << snd_strerror(err) << "\n";
        snd_pcm_hw_params_free(hw_params);
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 设置采样率
    if ((err = snd_pcm_hw_params_set_rate_near(capture_handle, hw_params, &sample_rate, 0)) < 0) {
        std::cerr << "无法设置采样率: " << snd_strerror(err) << "\n";
        snd_pcm_hw_params_free(hw_params);
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 设置通道数
    if ((err = snd_pcm_hw_params_set_channels(capture_handle, hw_params, channels)) < 0) {
        std::cerr << "无法设置通道数: " << snd_strerror(err) << "\n";
        snd_pcm_hw_params_free(hw_params);
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 应用硬件参数
    if ((err = snd_pcm_hw_params(capture_handle, hw_params)) < 0) {
        std::cerr << "无法设置参数: " << snd_strerror(err) << "\n";
        snd_pcm_hw_params_free(hw_params);
        snd_pcm_close(capture_handle);
        return;
    }
    
    // 释放硬件参数结构
    snd_pcm_hw_params_free(hw_params);
    
    // 准备录音
    if ((err = snd_pcm_prepare(capture_handle)) < 0) {
        std::cerr << "无法准备音频接口: " << snd_strerror(err) << "\n";
        snd_pcm_close(capture_handle);
        return;
    }
    
    std::cout << "音频捕获已启动\n";
    
    // 分配缓冲区
    const int buffer_frames = 1024;
    int16_t buffer[buffer_frames * channels];
    
    // 捕获循环
    while (g_running) {
        // 从麦克风读取音频
        int frames = snd_pcm_readi(capture_handle, buffer, buffer_frames);
        
        if (frames < 0) {
            // 处理错误
            frames = snd_pcm_recover(capture_handle, frames, 0);
            if (frames < 0) {
                std::cerr << "从音频接口读取失败: " << snd_strerror(frames) << "\n";
                break;
            }
            continue;
        }
        
        // 将音频数据传递给唤醒检测器
        detector.processAudio(buffer, frames);
    }
    
    // 清理
    snd_pcm_close(capture_handle);
    std::cout << "音频捕获已停止\n";
}

int main(int argc, char* argv[]) {
    // 注册信号处理器，捕获Ctrl+C
    signal(SIGINT, signalHandler);
    
    std::cout << "====== 外部音频流唤醒测试程序 ======\n";
    std::cout << "本程序将从麦克风捕获音频并通过外部流方式传递给唤醒检测器\n";
    std::cout << "按Ctrl+C退出程序\n";
    
    // 创建唤醒检测器
    WakeUpDetector detector;
    
    // 设置回调
    detector.setWakeUpCallback(onWakeUp);
    
    // 启动音频捕获线程
    std::thread capture_thread(captureAudio, std::ref(detector));
    
    // 等待唤醒或用户中断
    int seconds = 0;
    while (g_running) {
        if (g_wake_up_detected) {
            std::cout << "检测到唤醒词! 继续监听中...\n";
            g_wake_up_detected = false;
        }
        
        std::cout << "正在监听... (已运行 " << seconds << " 秒)\r" << std::flush;
        std::this_thread::sleep_for(std::chrono::seconds(1));
        seconds++;
    }
    
    std::cout << "\n正在停止唤醒检测...\n";
    
    // 等待捕获线程结束
    if (capture_thread.joinable()) {
        capture_thread.join();
    }
    
    std::cout << "测试程序已退出\n";
    return 0;
} 