#include "../include/internal/ivw_wrapper.h"
#include "../include/sample_common.h"
#include "../include/speech_recognizer.h"
#include "../include/audio_buffer.h"
#include "../include/config.h"
#include <string>
#include <iostream>
#include <atomic>
#include <mutex>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// 静态变量
static IvwCallback g_ivwCallback = nullptr;
static std::mutex g_callbackMutex;
static std::atomic<bool> g_isRunning{false};
static struct speech_rec g_ivwRec;

// 音频回调函数，用于外部获取音频数据
static AudioCaptureCallback g_audioCaptureCallback = nullptr;
static std::mutex g_audioCaptureCallbackMutex;


// 用于注册aikit回调的静态函数
static void OnOutput(AIKIT_HANDLE *handle, const AIKIT_OutputData *output)
{
    if (!strcmp(handle->abilityID, IVW_ABILITY))
    {
        try
        {
            json j = json::parse((char *)output->node->value);
            if (j.contains("rlt") && !j["rlt"].empty())
            {
                auto &result = j["rlt"][0];
                std::string wake_word;
                int confidence = 0;

                if (result.contains("keyword"))
                {
                    wake_word = result["keyword"].get<std::string>();
                }

                if (result.contains("score"))
                {
                    confidence = result["score"].get<int>();
                }
                else if (result.contains("confidence"))
                {
                    confidence = result["confidence"].get<int>();
                }

                // 调用用户回调
                std::lock_guard<std::mutex> lock(g_callbackMutex);
                if (g_ivwCallback)
                {
                    g_ivwCallback(wake_word, confidence);
                }
            }
        }
        catch (const std::exception &e)
        {
            std::cerr << "Error parsing JSON: " << e.what() << std::endl;
        }
    }
}

static void OnEvent(AIKIT_HANDLE *handle, AIKIT_EVENT eventType, const AIKIT_OutputEvent *eventValue)
{
    std::cout << "OnEvent:" << eventType << std::endl;
}

static void OnError(AIKIT_HANDLE *handle, int32_t err, const char *desc)
{
    std::cerr << "OnError:" << err << " - " << desc << std::endl;
}


void setAudioCaptureCallback(AudioCaptureCallback callback)
{
    std::lock_guard<std::mutex> lock(g_audioCaptureCallbackMutex);
    g_audioCaptureCallback = std::move(callback);
}

// 音频数据回调函数，传递给声卡录音
void AudioCallback(const int16_t *samples, size_t count)
{
    // 调用外部音频回调
    std::lock_guard<std::mutex> lock(g_audioCaptureCallbackMutex);
    if (g_audioCaptureCallback)
    {
        g_audioCaptureCallback(samples, count);
    }
    
    // 保存到音频缓冲区
    g_audioBuffer.addSamples(samples, count);
}

bool initIvwEngine(const std::string& resource_path, const std::string& keyword_file, IvwCallback callback)
{
    // 保存回调函数
    {
        std::lock_guard<std::mutex> lock(g_callbackMutex);
        g_ivwCallback = std::move(callback);
    }
    
    // 设置回调
    AIKIT_Callbacks cbs = {OnOutput, OnEvent, OnError};
    AIKIT_RegisterAbilityCallback(IVW_ABILITY, cbs);
    
    // 初始化AIKIT
    const char *ability_id = "e867a88f2";
    std::string res_dir = resource_path.empty() ? RESOURCE_PATH : resource_path;
    
    AIKIT_Configurator::builder()
        .app()
        .appID("83bfd589")
        .apiSecret("ZDJiM2QwZjU1NTIzZDI0Y2E5YmY3NDk2")
        .apiKey("f9b2c6ef4ffc8f71b2fb870c8c789dc0")
        .workDir("./")
        .resDir(res_dir.c_str())
        .auth()
        .authType(0)
        .ability(ability_id)
        .log()
        .logLevel(LOG_LVL_INFO)
        .logMode(2)
        .logPath("./aikit.log");

    int ret = AIKIT_Init();
    if (ret != 0)
    {
        std::cerr << "AIKIT_Init failed: " << ret << std::endl;
        return false;
    }
    
    // 初始化唤醒引擎
    ret = AIKIT_EngineInit(IVW_ABILITY, nullptr);
    if (ret != 0)
    {
        std::cerr << "AIKIT_EngineInit failed: " << ret << std::endl;
        return false;
    }
    
    // 加载关键词
    std::string kw_file = keyword_file.empty() ? (res_dir + "/ivw70/many-keywords.txt") : keyword_file;
    
    AIKIT_CustomData customData;
    customData.key = "key_word";
    customData.index = 0;
    customData.from = AIKIT_DATA_PTR_PATH;
    customData.value = (void *)(kw_file.c_str());
    customData.len = kw_file.length();
    customData.next = nullptr;
    customData.reserved = nullptr;
    
    ret = AIKIT_LoadData(IVW_ABILITY, &customData);
    if (ret != 0)
    {
        std::cerr << "AIKIT_LoadData failed: " << ret << std::endl;
        return false;
    }
    
    return true;
}

bool startIvwWithMicrophone()
{
    if (g_isRunning)
    {
        std::cerr << "唤醒检测已经在运行中" << std::endl;
        return false;
    }
    
    // 初始化语音识别器 - 使用麦克风模式
    int ret = sr_init(&g_ivwRec, 1, IVW_ABILITY, SR_MIC);
    if (ret != 0)
    {
        std::cerr << "初始化语音识别器失败: " << ret << std::endl;
        return false;
    }
    
    // 设置音频回调
    sr_set_audio_callback(&g_ivwRec, AudioCallback);
    
    // 开始监听
    ret = sr_start_listening(&g_ivwRec);
    if (ret != 0)
    {
        std::cerr << "开始监听失败: " << ret << std::endl;
        sr_uninit(&g_ivwRec);
        return false;
    }
    
    g_isRunning = true;
    return true;
}

/**
 * 启动唤醒检测，使用外部音频输入模式
 * 不会启动麦克风捕获，而是准备好接收外部音频数据
 */
bool startIvwWithExternalAudio()
{
    if (g_isRunning)
    {
        std::cerr << "唤醒检测已经在运行中" << std::endl;
        return false;
    }
    
    // 初始化语音识别器 - 使用用户输入模式（非麦克风模式）
    int ret = sr_init(&g_ivwRec, 1, IVW_ABILITY, SR_USER);
    if (ret != 0)
    {
        std::cerr << "初始化语音识别器失败: " << ret << std::endl;
        return false;
    }
    
    // 设置音频回调（用于可能的音频处理，不是从麦克风捕获）
    sr_set_audio_callback(&g_ivwRec, AudioCallback);
    
    // 开始监听 - 准备接收外部数据
    ret = sr_start_listening(&g_ivwRec);
    if (ret != 0)
    {
        std::cerr << "开始监听失败: " << ret << std::endl;
        sr_uninit(&g_ivwRec);
        return false;
    }
    
    g_isRunning = true;
    return true;
}

bool processIvwAudio(const int16_t* audio_data, size_t length)
{
    if (!g_isRunning)
    {
        std::cerr << "请先启动唤醒检测" << std::endl;
        return false;
    }
    
    // 添加到音频缓冲区
    g_audioBuffer.addSamples(audio_data, length);
    
    //    // 打印部分采集的数据，用于验证音频采集正常工作
    // if (length > 0) {
    //     std::cout << "接收到音频数据: " << length << " 采样点" << std::endl;
    //     // 打印前10个采样点的值（如果有）
    //     size_t samples_to_print = std::min(length, static_cast<size_t>(10));
    //     std::cout << "前" << samples_to_print << "个采样点的值: ";
    //     for (size_t i = 0; i < samples_to_print; ++i) {
    //         std::cout << audio_data[i] << " ";
    //     }
    //     std::cout << std::endl;
        
    //     // 计算并打印音频数据的统计信息
    //     int16_t min_val = INT16_MAX;
    //     int16_t max_val = INT16_MIN;
    //     int64_t sum = 0;
        
    //     for (size_t i = 0; i < length; ++i) {
    //         min_val = std::min(min_val, audio_data[i]);
    //         max_val = std::max(max_val, audio_data[i]);
    //         sum += audio_data[i];
    //     }
        
    //     double avg = static_cast<double>(sum) / length;
    //     std::cout << "音频统计: 最小值=" << min_val << ", 最大值=" << max_val 
    //               << ", 平均值=" << avg << std::endl;
    // }
    // 将音频数据直接写入语音识别器
    // 注意：这里将int16_t数据转换为char*，并计算相应的字节长度
    int ret = sr_write_audio_data(&g_ivwRec, (char*)audio_data, length * sizeof(int16_t));
    if (ret != 0) {
        std::cerr << "写入音频数据失败: " << ret << std::endl;
        return false;
    }
    
    return true;
}

bool stopIvw()
{
    if (!g_isRunning)
    {
        return true; // 已经停止，直接返回成功
    }
    
    // 停止监听
    int ret = sr_stop_listening(&g_ivwRec);
    if (ret != 0)
    {
        std::cerr << "停止监听失败: " << ret << std::endl;
        return false;
    }
    
    // 清理资源
    sr_uninit(&g_ivwRec);
    
    g_isRunning = false;
    return true;
}

void uninitIvwEngine()
{
    // 确保已停止
    stopIvw();
    
    // 卸载数据
    AIKIT_UnLoadData(IVW_ABILITY, "key_word", 0);
    
    // 释放引擎
    AIKIT_EngineUnInit(IVW_ABILITY);
    
    // 清理AIKIT
    AIKIT_UnInit();
    
    // 清除回调
    {
        std::lock_guard<std::mutex> lock(g_callbackMutex);
        g_ivwCallback = nullptr;
    }
    
    {
        std::lock_guard<std::mutex> lock(g_audioCaptureCallbackMutex);
        g_audioCaptureCallback = nullptr;
    }
} 