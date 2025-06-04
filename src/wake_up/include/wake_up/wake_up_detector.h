#ifndef WAKE_UP_DETECTOR_H
#define WAKE_UP_DETECTOR_H

#include <string>
#include <functional>
#include <memory>
#include <atomic>

// 前向声明，隐藏实现细节
class WakeUpDetectorImpl;

/**
 * @brief 唤醒检测器类，提供语音唤醒功能
 * 
 * 该类提供两种使用方式：
 * 1. 直接从麦克风捕获音频并进行唤醒检测
 * 2. 接收外部提供的音频数据并进行唤醒检测
 */
class WakeUpDetector {
public:
    /**
     * @brief 构造函数
     * 
     * @param resource_path 资源文件路径，默认为空使用内部路径
     * @param keyword_file 关键词文件路径，默认为空使用内部默认关键词
     */
    WakeUpDetector(const std::string& resource_path = "", const std::string& keyword_file = "");
    
    /**
     * @brief 析构函数，释放资源
     */
    ~WakeUpDetector();
    
    // 禁用拷贝构造和拷贝赋值
    WakeUpDetector(const WakeUpDetector&) = delete;
    WakeUpDetector& operator=(const WakeUpDetector&) = delete;
    
    /**
     * @brief 唤醒回调函数类型
     * 
     * @param keyword 检测到的唤醒词
     * @param confidence 置信度分数
     */
    using WakeUpCallback = std::function<void(const std::string& keyword, int confidence)>;
    
    /**
     * @brief 设置唤醒回调函数
     * 
     * @param callback 回调函数，在检测到唤醒词时被调用
     */
    void setWakeUpCallback(WakeUpCallback callback);
    
    /**
     * @brief 从麦克风启动唤醒检测
     * 
     * @return true 成功启动
     * @return false 启动失败
     */
    bool startWithMicrophone();
    
    /**
     * @brief 停止唤醒检测
     * 
     * @return true 成功停止
     * @return false 停止失败
     */
    bool stop();
    
    /**
     * @brief 处理外部提供的音频数据
     * 
     * @param audio_data 音频数据，16位PCM格式，16kHz采样率，单声道
     * @param length 数据长度（样本数）
     * @return true 处理成功
     * @return false 处理失败
     */
    bool processAudio(const int16_t* audio_data, size_t length);
    
    /**
     * @brief 检查唤醒检测是否正在运行
     * 
     * @return true 正在运行
     * @return false 未运行
     */
    bool isRunning() const;
    
private:
    // 使用PIMPL模式隐藏实现细节
    std::unique_ptr<WakeUpDetectorImpl> impl_;
    std::atomic<bool> running_{false};
};

#endif // WAKE_UP_DETECTOR_H 