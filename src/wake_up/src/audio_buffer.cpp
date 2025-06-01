#include "audio_buffer.h"
#include <algorithm>
#include <sndfile.h>

AudioBuffer g_audioBuffer;

AudioBuffer::AudioBuffer(int sampleRate, int channels)
    : sampleRate_(sampleRate), channels_(channels) {
    // 默认缓存10秒的音频
    maxBufferSize_ = sampleRate * channels * 10;
}

AudioBuffer::~AudioBuffer() {
    clear();
}

void AudioBuffer::addSamples(const int16_t* samples, size_t count) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    //    // 添加调试信息
    // uint64_t currentTime = getTimeMs();
    // printf("Adding samples: count=%zu, time_since_last_update=%lums\n", 
    //        count, currentTime - lastUpdateTime_);
    // lastUpdateTime_ = currentTime;

    // 添加新样本
    for (size_t i = 0; i < count; ++i) {
        buffer_.push_back(samples[i]);
    }
    
    // 如果缓冲区超过最大大小，移除旧的样本
    while (buffer_.size() > maxBufferSize_) {
        buffer_.pop_front();
    }
    //     // 打印缓冲区状态
    // printBufferInfo();
}

std::vector<int16_t> AudioBuffer::getLastAudio(int durationMs) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    // 计算需要的样本数
    size_t samplesNeeded = (durationMs * sampleRate_ * channels_) / 1000;
    samplesNeeded = std::min(samplesNeeded, buffer_.size());
    
    // 提取最近的音频数据
    std::vector<int16_t> audio(samplesNeeded);
    auto startIt = buffer_.end() - samplesNeeded;
    std::copy(startIt, buffer_.end(), audio.begin());
    
    return audio;
}

bool AudioBuffer::saveToWav(const std::vector<int16_t>& audio, const char* filename) {
    SF_INFO sfinfo;
    sfinfo.samplerate = sampleRate_;
    sfinfo.channels = channels_;
    sfinfo.format = SF_FORMAT_WAV | SF_FORMAT_PCM_16;
    
    SNDFILE* file = sf_open(filename, SFM_WRITE, &sfinfo);
    if (!file) {
        return false;
    }
    
    // 写入音频数据
    sf_write_short(file, audio.data(), audio.size());
    
    sf_close(file);
    return true;
}

void AudioBuffer::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    buffer_.clear();
} 