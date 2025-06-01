#ifndef AUDIO_BUFFER_H
#define AUDIO_BUFFER_H

#include <vector>
#include <deque>
#include <mutex>
#include <sndfile.h>
#include <chrono>

class AudioBuffer
{
public:
    AudioBuffer(int sampleRate = 16000, int channels = 1);
    ~AudioBuffer();

    // 添加音频数据到缓冲区
    void addSamples(const int16_t *samples, size_t count);

    // 获取最近的音频数据
    std::vector<int16_t> getLastAudio(int durationMs);

    // 保存音频到WAV文件
    bool saveToWav(const std::vector<int16_t> &audio, const char *filename);

    // 清空缓冲区
    void clear();

    // 获取缓冲区
    std::deque<int16_t> getBuffer()
    {
        std::lock_guard<std::mutex> lock(mutex_);
        return buffer_;
    }

    // 添加调试函数
    void printBufferInfo() 
    {
        // std::lock_guard<std::mutex> lock(mutex_); //这里不能有锁，否则会死锁
        printf("Buffer size: %zu/%zu\n", buffer_.size(), maxBufferSize_);
        if (!buffer_.empty())
        {
            printf("First sample: %d, Last sample: %d\n",
                   buffer_.front(), buffer_.back());
        }
    }

    // 添加时间戳
    uint64_t lastUpdateTime_{0};
    uint64_t getTimeMs()
    {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
                   std::chrono::system_clock::now().time_since_epoch())
            .count();
    }

private:
    std::deque<int16_t> buffer_;
    std::mutex mutex_;
    int sampleRate_;
    int channels_;
    size_t maxBufferSize_; // 最大缓冲区大小（以样本数为单位）
};

// 全局音频缓冲区
extern AudioBuffer g_audioBuffer;

#endif // AUDIO_BUFFER_H
