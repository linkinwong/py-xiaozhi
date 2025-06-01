// #include <Python.h>
#include <pybind11/embed.h>
#include "who_says_what.hpp"
#include <gperftools/profiler.h>           // CPU分析器
#include <gperftools/heap-profiler.h>      // 堆内存分析器
#include <gperftools/heap-checker.h>       // 堆内存检查器

// std::unique_ptr<VoiceEncoder> WhoSaysWhat::voice_encoder;
// iflytek::AudioProcessor WhoSaysWhat::audio_processor;
// FILE *fin = nullptr;
// std::vector<std::vector<float>> WhoSaysWhat::mfcc_features(100, std::vector<float>(42, 0.4f));

// 定义一个全局变量，用于记录是否需要记录唤醒词
bool record_wakeup = false;
// 定义全局变量，用于控制是否进行性能分析
bool enable_profiling = false;

WhoSaysWhat::WhoSaysWhat(const std::string &node_name)
    : Node(node_name)
{
    // 初始化future
    ivw_exit_future = ivw_exit_promise.get_future();

    // 创建声纹操作服务
    add_voice_print_srv_ = this->create_service<AudioAddRecognition>(
        "/audio/add_recognition",
        std::bind(&WhoSaysWhat::handle_add_voice_print, this,
                  std::placeholders::_1, std::placeholders::_2));

    remove_voice_print_srv_ = this->create_service<AudioRemoveRecognition>(
        "/audio/remove_recognition",
        std::bind(&WhoSaysWhat::handle_remove_voice_print, this,
                  std::placeholders::_1, std::placeholders::_2));

    RCLCPP_INFO(this->get_logger(), "Voice print add and remove services are ready");

    init();

    RCLCPP_INFO(this->get_logger(), "WhoSaysWhat node initialization completed");

    // 创建一个线程来处理语音唤醒
    ivw_thread_ = std::thread([this]()
                              {
                                  AIKIT_Callbacks cbs = {OnOutput, OnEvent, OnError};
                                  TestIvw70(cbs);
                                  // 通知主线程ivw已经结束
                                  ivw_exit_promise.set_value(); });
}

WhoSaysWhat::~WhoSaysWhat()
{
    // if (fin)
    // {
    //     fclose(fin);
    // }

    if (ivw_thread_.joinable())
    {
        ivw_thread_.join();
        RCLCPP_INFO(this->get_logger(), "ivw_thread_ finished.");
    }

    AIKIT_UnInit();

    // 在清理 Python 相关资源之前，确保获取 GIL
    {
        pybind11::gil_scoped_acquire acquire;
        // 清理声纹识别资源
        voice_recognition::cleanup_voice_recog();
    }

    RCLCPP_INFO(this->get_logger(), "WhoSaysWhat node cleaned up successfully");
}

void WhoSaysWhat::init()
{

    // 初始化声纹识别器
    // voice_encoder = std::make_unique<VoiceEncoder>();
    // if (!voice_encoder->load_model(RESOURCE_PATH "/voice_print/voiceprint_model.bin"))
    // {
    //     RCLCPP_ERROR(this->get_logger(), "Failed to load voice print model!");
    //     return;
    // }

    // voice_encoder->model_introspection();

    // 初始化audio_processor
    // if (!init_audio_processor())
    // {
    //     RCLCPP_ERROR(this->get_logger(), "Failed to init audio processor!");
    //     return;
    // }

    // 初始化声纹识别器
    // if (!init_voice_encoder())
    // {
    //     RCLCPP_ERROR(this->get_logger(), "Failed to init voice encoder!");
    //     return;
    // }

    const char *ability_id = "e867a88f2;e75f07b62;e2e44feff";
    if (strlen(ability_id) == 0)
    {
        RCLCPP_ERROR(this->get_logger(), "ability_id is empty!!");
        return;
    }

    // 打印出 ./ 的具体值
    RCLCPP_INFO(this->get_logger(), "Current working directory: %s", getcwd(NULL, 0));
    // 打印出 ./ 的具体值
    RCLCPP_INFO(this->get_logger(), "Target arch is: %s", TARGET_ARCH);
    AIKIT_Configurator::builder()
        .app()
        .appID("83bfd589")
        .apiSecret("ZDJiM2QwZjU1NTIzZDI0Y2E5YmY3NDk2")
        .apiKey("f9b2c6ef4ffc8f71b2fb870c8c789dc0")
        .workDir("./")
        .resDir(RESOURCE_PATH)
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
        RCLCPP_ERROR(this->get_logger(), "AIKIT_Init failed: %d", ret);
        return;
    }

    try
    {
        RCLCPP_INFO(this->get_logger(), "Starting voice recognition initialization...");

        // 在初始化声纹识别时显式管理 GIL
        {
            pybind11::gil_scoped_acquire acquire;
            voice_recognition::init_voice_recog();
            RCLCPP_INFO(this->get_logger(), "Voice recognition initialized successfully");
        } // GIL 在这里被释放
    }
    catch (const std::exception &e)
    {
        RCLCPP_ERROR(this->get_logger(), "Failed to initialize voice recognition: %s", e.what());
        throw;
    }
}

// bool WhoSaysWhat::init_audio_processor()
// {
//     iflytek::AudioPreprocessConfig audio_process_config;
//     iflytek::MFCCConfig mfcc_config;
//     iflytek::FbankConfig fbank_config;
//     return audio_processor.init(audio_process_config, mfcc_config, fbank_config);
// }

// bool WhoSaysWhat::init_voice_encoder()
// {
//     iflytek::VoiceprintConfig config;
//     return voice_encoder->init(config);
// }

void WhoSaysWhat::OnOutput(AIKIT_HANDLE *handle, const AIKIT_OutputData *output)
{
    if (!strcmp(handle->abilityID, IVW_ABILITY))
    {
        // printf("OnOutput value:%s\n", (char *)output->node->value);

        // 记录开始时间
        TimePoint start_time = Clock::now();

        // 如果启用了性能分析，在此处生成堆内存快照
        if (enable_profiling) {
            HeapProfilerDump("Before_VoiceRecognition");
        }

        // 解析JSON结果
        try
        {
            json j = json::parse((char *)output->node->value);
            if (j.contains("rlt") && !j["rlt"].empty())
            {
                auto &result = j["rlt"][0];
                std::string wake_word;
                int duration = 0;

                if (result.contains("keyword"))
                {
                    wake_word = result["keyword"].get<std::string>();
                }

                if (result.contains("iduration"))
                {
                    duration = result["iduration"].get<int>() * 10;
                    int captureMs = std::max(2200, duration+140);
                    // auto audio = g_audioBuffer.getLastAudio(captureMs);

		    // // 把audio保存为wav格式的文件，采样率16k，16位，单通道。文件名是wake_word.wav
            //         if (record_wakeup) {
            //             std::string wav_file_name ="recorded" + wake_word + ".wav";
            //             if (!g_audioBuffer.saveToWav(audio, wav_file_name.c_str())) {
            //                 RCLCPP_ERROR(rclcpp::get_logger("who_says_what"), "Failed to save WAV file: %s", wav_file_name.c_str());
            //             }
            //         }

                    std::string name = "fake_name";
                    float score = 0.0;

                    // // 临时释放 GIL，因为当前线程可能已经持有它
                    // pybind11::gil_scoped_release release;
                    // {
                    //     pybind11::gil_scoped_acquire acquire;

                    //     try
                    //     {
                    //         // 如果启用了性能分析，在声纹识别前生成堆内存快照
                    //         if (enable_profiling) {
                    //             HeapProfilerDump("Before_Recognize_Voice");
                    //         }
                            
                    //         std::tie(name, score) = voice_recognition::recognize_voice(
                    //             audio,        //
                    //             audio.size(), // 元素个数
                    //             16000);
                                
                    //         // 如果启用了性能分析，在声纹识别后生成堆内存快照
                    //         if (enable_profiling) {
                    //             HeapProfilerDump("After_Recognize_Voice");
                    //         }
                    //     }
                    //     catch (const std::exception &e)
                    //     {
                    //         RCLCPP_ERROR(rclcpp::get_logger("who_says_what"), "Voice recognition failed: %s", e.what());
                    //         name = "unknown";
                    //         score = 0.0;
                    //     }
                    // } // 重新获取 GIL

                    auto end_time = Clock::now();
                    auto process_time = std::chrono::duration_cast<std::chrono::milliseconds>(
                                            end_time - start_time)
                                            .count();

                    // 处理识别结果
                    if (!name.empty())
                    {
                        printf("\n=== 声纹识别结果 ===\n");
                        printf("命令词: %s\n", wake_word.c_str());
                        printf("说话人: %s (置信度: %.2f)\n", name.c_str(), score);
                        printf("人声时长: %d ms (VAD applied)\n", duration);
                        printf("处理时长: %ld ms\n", process_time);
                        printf("===================\n\n");

                        // 发布结果
                        try
                        {
                            CommandWordPublisher::getInstance()->publishCommandWord(wake_word, name);
                            WakeUpPublisher::getInstance()->publishWakeUp(true);
                        }
                        catch (const std::exception &e)
                        {
                            RCLCPP_ERROR(rclcpp::get_logger("who_says_what"),
                                         "Failed to publish results: %s", e.what());
                        }
                    }
                }
            }
        }
        catch (const std::exception &e)
        {
            RCLCPP_ERROR(rclcpp::get_logger("who_says_what"), "Error parsing JSON: %s", e.what());
        }
        
        // 如果启用了性能分析，在此处生成堆内存快照
        if (enable_profiling) {
            HeapProfilerDump("After_VoiceRecognition");
        }
    }
}

void WhoSaysWhat::OnEvent(AIKIT_HANDLE *handle, AIKIT_EVENT eventType, const AIKIT_OutputEvent *eventValue)
{
    printf("OnEvent:%d\n", eventType);
    // if (eventType == AIKIT_Event_End)
    // {
    //     ttsFinished = true;
    // }
}

void WhoSaysWhat::OnError(AIKIT_HANDLE *handle, int32_t err, const char *desc)
{
    printf("OnError:%d\n", err);
}

void WhoSaysWhat::handle_add_voice_print(
    const std::shared_ptr<AudioAddRecognition::Request> request,
    std::shared_ptr<AudioAddRecognition::Response> response)
{
    RCLCPP_INFO(this->get_logger(), "Attempting to add voice print for: %s", request->name.c_str());

    // 临时释放 GIL，因为当前线程可能已经持有它
    pybind11::gil_scoped_release release;
    {
        pybind11::gil_scoped_acquire acquire;

        response->status = voice_recognition::register_voice(request->name, request->audio, 16000); // 临时设置为true，需要实现实际的添加逻辑
    }

    if (response->status)
    {
        RCLCPP_INFO(this->get_logger(), "Successfully added voice print for: %s", request->name.c_str());
    }
    else
    {
        RCLCPP_ERROR(this->get_logger(), "Failed to add voice print for: %s", request->name.c_str());
    }
}

void WhoSaysWhat::handle_remove_voice_print(
    const std::shared_ptr<AudioRemoveRecognition::Request> request,
    std::shared_ptr<AudioRemoveRecognition::Response> response)
{
    RCLCPP_INFO(this->get_logger(), "Attempting to remove voice print for: %s", request->name.c_str());

    // 临时释放 GIL，因为当前线程可能已经持有它
    pybind11::gil_scoped_release release;
    {
        pybind11::gil_scoped_acquire acquire;

        RCLCPP_INFO(this->get_logger(), "Attempting to remove voice print...");
        response->status = voice_recognition::remove_user(request->name);
    }

    if (response->status)
    {
        RCLCPP_INFO(this->get_logger(), "Successfully removed voice print for: %s", request->name.c_str());
        RCLCPP_INFO(this->get_logger(), "Updated voice print model information:");
        // voice_encoder->model_introspection();
    }
    else
    {
        RCLCPP_ERROR(this->get_logger(), "Failed to remove voice print for: %s (voice print may not exist)", request->name.c_str());
    }
}

// 主函数入口
int main(int argc, char *argv[])
{
    // 实现：如果传入了1个额外参数 "record", 则记录唤醒词，并保存为wav文件
    if (argc >= 2) {
        if (std::string(argv[1]) == "record") {
            record_wakeup = true;
        }
        if (std::string(argv[1]) == "profile" || (argc >= 3 && std::string(argv[2]) == "profile")) {
            enable_profiling = true;
        }
    }
    
    
    setbuf(stdout, NULL);

    // pybind11::scoped_interpreter guard{};
    // rclcpp::init(argc, argv);
    auto node = std::make_shared<WhoSaysWhat>("who_says_what");

    // // 创建一个单独的线程来运行executor
    // std::thread spinner([node]()
    //                     {
    //     rclcpp::executors::SingleThreadedExecutor executor;
    //     executor.add_node(node);
    //     executor.spin(); });

    // // 等待ivw退出
    // node->ivw_exit_future.wait();

    // // 关闭ROS节点
    // RCLCPP_INFO(node->get_logger(), "IVW has finished, shutting down ROS...");
    // rclcpp::shutdown();

    // 等待spinner线程结束
    if (spinner.joinable())
    {
        spinner.join();
        RCLCPP_INFO(node->get_logger(), "spinner finished.");
    }

    // 清理node
    node.reset();

    // 如果启用了性能分析，则停止分析器
    if (enable_profiling) {
        ProfilerStop();  // 停止CPU性能分析
        HeapProfilerDump("Final heap dump");  // 生成一次堆内存快照
        HeapProfilerStop();  // 停止堆内存分析
        printf("Performance profiling completed.\n");
    }

    RCLCPP_INFO(rclcpp::get_logger("main"), "Clean shutdown completed");
    return 0;
}
