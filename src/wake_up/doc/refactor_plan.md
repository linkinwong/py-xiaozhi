# Wake Up 模块重构计划（修订版）

## 当前代码结构分析

### 概述
当前 `wake_up` 模块集成了多种功能：
- 语音唤醒（Wake Word Detection）
- 声纹识别（Voice Print Recognition）
- ROS 通信（发布唤醒消息）

目标是将其重构为只包含唤醒功能的 SDK 库（.so），可以被其他应用集成使用。

### 主要文件分析

#### 1. CMakeLists.txt
已经进行了部分修改，移除了：
- ROS 相关依赖（ament_cmake, rclcpp 等）
- Python 和 pybind11 相关依赖（声纹识别部分）
- gperftools 性能分析工具依赖

保留了：
- nlohmann_json 依赖（用于解析 JSON 数据）
- 基本的 C++ 编译选项
- 路径配置（资源路径、库路径等）

#### 2. 核心代码文件
- **who_says_what.cpp/hpp**：主程序入口，包含 ROS 节点、声纹识别和唤醒功能
- **ivw.cpp**：唤醒功能核心实现（**将尽量保持不变, 但是必要的修改是 ok 的，使结构更清晰的重构是允许的**）
- **audio_buffer.cpp/h**：音频缓冲区管理
- **speech_recognizer.cpp/h**：语音识别相关功能
- **linuxrec.c/h**：Linux 录音功能实现

#### 3. 依赖分析
- **外部依赖**：
  - aikit 库（唤醒功能的底层实现，**将静态链接**）
  - asound 库（ALSA，音频捕获）
  - sndfile 库（音频文件处理）
  - nlohmann_json 库（JSON 解析）
  - ~~ROS 相关库（已移除）~~
  - ~~Python/pybind11（已移除，用于声纹识别）~~

- **内部依赖**：
  - 唤醒功能依赖于音频缓冲区和音频捕获功能
  - ~~原 ROS 通信依赖于唤醒功能的输出~~ 唤醒功能的输出，不再使用 ROS 通信传递，而是通过回调函数传递
  - 

## 重构计划

### 1. 库结构设计

将唤醒功能封装为一个 C++ 类库，对外提供简洁的 API：

```cpp
class WakeUpDetector {
public:
    // 构造函数，可设置资源路径、关键词等
    WakeUpDetector(const std::string& resource_path = "", const std::string& keyword_file = "");
    ~WakeUpDetector();

    // 回调函数类型定义
    using WakeUpCallback = std::function<void(const std::string& keyword, int confidence)>;
    
    // 设置唤醒回调
    void setWakeUpCallback(WakeUpCallback callback);
    
    // 启动唤醒检测（直接从麦克风）
    bool startWithMicrophone();
    
    // 启动唤醒检测（使用外部音频输入）
    bool startWithExternalAudio();
    
    // 停止唤醒检测
    bool stop();
    
    // 处理外部音频数据（用于从外部提供音频数据）
    bool processAudio(const int16_t* audio_data, size_t length);
    
    // 获取当前状态
    bool isRunning() const;

private:
    // 内部实现细节
};
```

### 2. 重构步骤

#### 步骤一：移除 ROS 和声纹识别相关代码
1. 删除 who_says_what.hpp/cpp 中 ROS 和声纹识别相关的代码
2. 创建新的 wake_up_detector.hpp/cpp 作为新的 API 入口
3. **保留 ivw.cpp 的核心代码，尽量减少修改**

#### 步骤二：解耦音频捕获与唤醒检测
1. 修改 ivw_wrapper.h/cpp，增加支持外部音频输入的初始化函数
2. 区分麦克风模式（SR_MIC）和用户输入模式（SR_USER）
3. 确保 processAudio 函数直接将音频数据传递给唤醒引擎，而不启动新的麦克风捕获

#### 步骤三：测试驱动开发
1. 创建两个测试程序：
   - **直接从麦克风捕获音频测试**：验证库可以直接从麦克风获取音频并唤醒
   - **外部音频流测试**：验证库可以处理外部应用程序捕获的音频流

2. 开发过程中不断运行这些测试程序，确保功能正确

#### 步骤四：修改 CMakeLists.txt 生成共享库
1. 将 add_executable 修改为 add_library，生成共享库
2. **静态链接 AIkit 库和相关资源**，减少外部依赖
3. 配置正确的安装路径和头文件导出

#### 步骤五：新增 SDK 演示程序
1. 创建两个演示程序：
   - 麦克风直接捕获示例
   - 外部音频流示例（使用成熟的音频捕获库）

### 3. 具体实现计划

#### 新文件结构
```
wake_up/
  ├── include/
  │   ├── wake_up/
  │   │   ├── wake_up_detector.h     # 新的 API 头文件
  │   │   └── audio_buffer.h         # 保留
  │   ├── internal/                  # 内部实现细节（不暴露给用户）
  │   │   ├── speech_recognizer.h
  │   │   ├── linuxrec.h
  │   │   └── ivw_wrapper.h          # 对 ivw.cpp 的简单包装
  │   └── config.h.in                # 配置头文件
  ├── src/
  │   ├── wake_up_detector.cpp       # 新的 API 实现
  │   ├── audio_buffer.cpp           # 保留
  │   ├── ivw.cpp                    # 保持核心代码不变
  │   ├── ivw_wrapper.cpp            # 简单包装，不大幅修改原逻辑
  │   ├── speech_recognizer.cpp      # 保留
  │   └── linuxrec.c                 # 保留
  ├── tests/
  │   ├── test_microphone.cpp        # 直接从麦克风捕获测试
  │   └── test_external_audio.cpp    # 外部音频流测试
  ├── example/
  │   ├── microphone_demo.cpp        # 从麦克风捕获示例
  │   └── external_audio_demo.cpp    # 外部音频流示例
  ├── CMakeLists.txt                 # 修改为生成共享库
  ├── resource/                      # 资源文件（可能会静态嵌入）
  └── libs/                          # 依赖库
```

#### CMakeLists.txt 修改要点
```cmake
# 查找外部依赖
find_package(nlohmann_json REQUIRED)
find_package(ALSA REQUIRED)
find_package(SndFile REQUIRED)

# 指定静态库的位置
set(AIKIT_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/libs/${TARGET_ARCH}")
set(AIKIT_STATIC_LIB "${AIKIT_LIB_DIR}/libaikit.a")

# 生成共享库
add_library(wake_up SHARED
  src/wake_up_detector.cpp
  src/audio_buffer.cpp
  src/ivw.cpp
  src/ivw_wrapper.cpp
  src/speech_recognizer.cpp
  src/linuxrec.c
)

# 设置版本号和 soname
set_target_properties(wake_up PROPERTIES
  VERSION 1.0.0
  SOVERSION 1
)

# 链接依赖库，静态链接 AIkit
target_link_libraries(wake_up
  PRIVATE
    ${AIKIT_STATIC_LIB}  # 静态链接 AIkit
    ALSA::ALSA
    SndFile::sndfile
    nlohmann_json::nlohmann_json
    pthread
)

# 添加测试程序
add_executable(test_microphone tests/test_microphone.cpp)
target_link_libraries(test_microphone wake_up)

add_executable(test_external_audio tests/test_external_audio.cpp)
target_link_libraries(test_external_audio wake_up)

# 添加示例程序
add_executable(microphone_demo example/microphone_demo.cpp)
target_link_libraries(microphone_demo wake_up)

add_executable(external_audio_demo example/external_audio_demo.cpp)
target_link_libraries(external_audio_demo wake_up)

# 安装目标
install(TARGETS wake_up
  LIBRARY DESTINATION lib
)

# 安装头文件（只安装公共API头文件）
install(DIRECTORY include/wake_up
  DESTINATION include
  FILES_MATCHING PATTERN "*.h"
)
```

## 测试驱动开发计划

### 1. 直接从麦克风捕获测试
实现一个简单的测试程序，验证库可以：
- 初始化唤醒检测器
- 从麦克风捕获音频
- 检测唤醒词并触发回调
- 正确释放资源

```cpp
// tests/test_microphone.cpp 概要
#include <wake_up/wake_up_detector.h>
#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>

std::atomic<bool> wake_up_detected(false);

void onWakeUp(const std::string& keyword, int confidence) {
    std::cout << "唤醒词检测到: " << keyword << ", 置信度: " << confidence << std::endl;
    wake_up_detected = true;
}

int main() {
    // 创建唤醒检测器
    WakeUpDetector detector;
    
    // 设置回调
    detector.setWakeUpCallback(onWakeUp);
    
    // 启动麦克风捕获
    if (!detector.startWithMicrophone()) {
        std::cerr << "无法启动麦克风捕获!" << std::endl;
        return 1;
    }
    
    // 等待唤醒或超时
    for (int i = 0; i < 30 && !wake_up_detected; i++) {
        std::cout << "请说唤醒词... (" << 30-i << "秒剩余)" << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    detector.stop();
    
    return wake_up_detected ? 0 : 1; // 成功返回0，失败返回1
}
```

### 2. 外部音频流测试
实现一个测试程序，验证库可以：
- 初始化唤醒检测器
- 使用外部音频模式启动（不启动麦克风）
- 从外部应用程序接收音频数据
- 处理这些数据并检测唤醒词
- 触发适当的回调

```cpp
// tests/test_external_audio.cpp 概要
#include <wake_up/wake_up_detector.h>
#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>
#include <alsa/asoundlib.h> // 使用成熟的ALSA库捕获音频

std::atomic<bool> wake_up_detected(false);

void onWakeUp(const std::string& keyword, int confidence) {
    std::cout << "唤醒词检测到: " << keyword << ", 置信度: " << confidence << std::endl;
    wake_up_detected = true;
}

// 音频捕获线程函数
void captureAudio(WakeUpDetector& detector) {
    // 使用ALSA初始化音频捕获
    snd_pcm_t *capture_handle;
    // ... 初始化ALSA音频捕获 ...
    
    // 缓冲区设置
    const int buffer_frames = 1024;
    int16_t buffer[buffer_frames];
    
    // 捕获循环
    while (!wake_up_detected) {
        // 从麦克风读取音频
        int frames = snd_pcm_readi(capture_handle, buffer, buffer_frames);
        if (frames > 0) {
            // 将音频数据传递给唤醒检测器
            detector.processAudio(buffer, frames);
        }
    }
    
    // 清理ALSA资源
    snd_pcm_close(capture_handle);
}

int main() {
    // 创建唤醒检测器
    WakeUpDetector detector;
    
    // 设置回调
    detector.setWakeUpCallback(onWakeUp);
    
    // 使用外部音频模式启动唤醒检测
    if (!detector.startWithExternalAudio()) {
        std::cerr << "启动唤醒检测失败" << std::endl;
        return 1;
    }
    
    // 启动音频捕获线程
    std::thread capture_thread(captureAudio, std::ref(detector));
    
    // 等待唤醒或超时
    for (int i = 0; i < 30 && !wake_up_detected; i++) {
        std::cout << "请说唤醒词... (" << 30-i << "秒剩余)" << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    // 如果未检测到唤醒词，则停止捕获
    if (!wake_up_detected) {
        wake_up_detected = true; // 设置标志以停止捕获线程
    }
    
    // 等待捕获线程结束
    if (capture_thread.joinable()) {
        capture_thread.join();
    }
    
    return wake_up_detected ? 0 : 1; // 成功返回0，失败返回1
}
```

## 注意事项与风险

1. **保留核心代码**：
   - 保持 ivw.cpp 核心代码~~不变~~ *大体不变，但是使结构更清晰的重构是允许的*，可考虑较小的修改集成
   - 确保回调机制和原有功能的一致性

2. **音频捕获与唤醒检测解耦**：
   - 确保在使用外部音频模式时不会启动麦克风捕获
   - 确保音频数据正确地传递给唤醒引擎进行处理

3. **静态链接考虑**：
   - AIkit 库静态链接可能增加库的大小
   - 需要确保资源文件的正确加载

4. **音频处理**：
   - 确保从外部应用获取的音频格式与库期望的格式一致
   - 处理可能的格式转换和采样率调整

5. **多线程安全**：
   - 音频处理和回调需要考虑线程安全
   - 避免死锁和竞态条件

6. **测试全面性**：
   - 确保两种测试场景都充分覆盖实际使用情况
   - 添加边缘情况测试和错误处理测试

## 实现优先级

1. 首先实现基本的包装类和简单API
2. 实现从麦克风直接捕获的功能和测试
3. 实现处理外部音频流的功能和测试
4. 添加更多高级功能和优化

## 简化实现策略

1. **使用成熟的库**：
   - 使用ALSA库进行音频捕获，不重新实现音频捕获功能
   - 使用现有的音频处理函数，不重新设计音频处理算法

2. **简洁的API设计**：
   - 保持API简单直观，避免过度设计
   - 提供最小必要的接口满足两种使用场景

3. **核心逻辑保持不变**：
   - 不重写已有的、已经验证过的唤醒功能核心代码
   - 添加必要的适配层使其满足新的使用方式 