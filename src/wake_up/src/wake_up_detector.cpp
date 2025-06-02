#include "../include/wake_up/wake_up_detector.h"
#include "../include/internal/ivw_wrapper.h"
#include "../include/audio_buffer.h"
#include <iostream>
#include <mutex>
#include <string>

// WakeUpDetector实现类
class WakeUpDetectorImpl {
public:
    WakeUpDetectorImpl(const std::string& resource_path, const std::string& keyword_file)
        : resource_path_(resource_path), keyword_file_(keyword_file) {}
    
    ~WakeUpDetectorImpl() {
        stop();
        uninitIvwEngine();
    }
    
    bool init(WakeUpDetector::WakeUpCallback callback) {
        callback_ = std::move(callback);
        
        // 设置内部回调函数
        auto ivwCallback = [this](const std::string& keyword, int confidence) {
            if (callback_) {
                callback_(keyword, confidence);
            }
        };
        
        return initIvwEngine(resource_path_, keyword_file_, ivwCallback);
    }
    
    bool startWithMicrophone() {
        return startIvwWithMicrophone();
    }
    
    bool processAudio(const int16_t* audio_data, size_t length) {
        return processIvwAudio(audio_data, length);
    }
    
    bool stop() {
        return stopIvw();
    }
    
private:
    std::string resource_path_;
    std::string keyword_file_;
    WakeUpDetector::WakeUpCallback callback_;
    std::mutex mutex_;
};

// WakeUpDetector类实现
WakeUpDetector::WakeUpDetector(const std::string& resource_path, const std::string& keyword_file)
    : impl_(new WakeUpDetectorImpl(resource_path, keyword_file)) {
}

WakeUpDetector::~WakeUpDetector() {
    stop();
}

void WakeUpDetector::setWakeUpCallback(WakeUpCallback callback) {
    impl_->init(std::move(callback));
}

bool WakeUpDetector::startWithMicrophone() {
    if (running_) {
        std::cerr << "唤醒检测已经在运行中" << std::endl;
        return false;
    }
    
    bool result = impl_->startWithMicrophone();
    if (result) {
        running_ = true;
    }
    return result;
}

bool WakeUpDetector::stop() {
    if (!running_) {
        return true; // 已经停止，直接返回成功
    }
    
    bool result = impl_->stop();
    if (result) {
        running_ = false;
    }
    return result;
}

bool WakeUpDetector::processAudio(const int16_t* audio_data, size_t length) {
    if (!running_) {
        std::cerr << "请先启动唤醒检测" << std::endl;
        return false;
    }
    
    return impl_->processAudio(audio_data, length);
}

bool WakeUpDetector::isRunning() const {
    return running_;
} 