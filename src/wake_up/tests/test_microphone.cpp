#include "../include/wake_up/wake_up_detector.h"
#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>
#include <csignal>

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

int main(int argc, char* argv[]) {
    // 注册信号处理器，捕获Ctrl+C
    signal(SIGINT, signalHandler);
    
    std::cout << "====== 麦克风唤醒测试程序 ======\n";
    std::cout << "本程序将从麦克风捕获音频并检测唤醒词\n";
    std::cout << "按Ctrl+C退出程序\n";
    
    // 创建唤醒检测器
    WakeUpDetector detector;
    
    // 设置回调
    detector.setWakeUpCallback(onWakeUp);
    
    // 启动麦克风捕获
    std::cout << "正在启动麦克风捕获...\n";
    if (!detector.startWithMicrophone()) {
        std::cerr << "启动麦克风捕获失败!\n";
        return 1;
    }
    
    std::cout << "麦克风捕获已启动，请说唤醒词...\n";
    
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
    detector.stop();
    
    std::cout << "测试程序已退出\n";
    return 0;
} 