#ifndef IVW_WRAPPER_H
#define IVW_WRAPPER_H

#include <string>
#include <functional>
#include <cstdint>  // 添加对int16_t的支持

/**
 * @brief 唤醒回调函数类型
 * 
 * @param keyword 唤醒词
 * @param confidence 置信度分数
 */
using IvwCallback = std::function<void(const std::string& keyword, int confidence)>;

/**
 * @brief 音频捕获回调函数类型
 * 
 * @param samples 音频样本
 * @param count 样本数量
 */
using AudioCaptureCallback = std::function<void(const int16_t* samples, size_t count)>;

/**
 * @brief 初始化唤醒引擎
 * 
 * @param resource_path 资源文件路径
 * @param keyword_file 关键词文件路径
 * @param callback 唤醒回调函数
 * @return true 初始化成功
 * @return false 初始化失败
 */
bool initIvwEngine(const std::string& resource_path, const std::string& keyword_file, IvwCallback callback);

/**
 * @brief 从麦克风启动唤醒检测
 * 
 * @return true 启动成功
 * @return false 启动失败
 */
bool startIvwWithMicrophone();

/**
 * @brief 启动唤醒检测，使用外部音频输入模式
 * 
 * 该函数不会启动麦克风捕获，而是准备好接收外部音频数据
 * 
 * @return true 启动成功
 * @return false 启动失败
 */
bool startIvwWithExternalAudio();

/**
 * @brief 处理外部音频数据
 * 
 * @param audio_data 音频数据
 * @param length 数据长度
 * @return true 处理成功
 * @return false 处理失败
 */
bool processIvwAudio(const int16_t* audio_data, size_t length);

/**
 * @brief 停止唤醒检测
 * 
 * @return true 停止成功
 * @return false 停止失败
 */
bool stopIvw();

/**
 * @brief 释放唤醒引擎资源
 */
void uninitIvwEngine();

/**
 * @brief 设置音频回调函数，用于音频缓冲
 * 
 * @param callback 回调函数
 */
void setAudioCaptureCallback(AudioCaptureCallback callback);

#endif // IVW_WRAPPER_H 