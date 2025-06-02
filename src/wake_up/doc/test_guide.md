# 唤醒模块测试指南

本文档介绍如何构建和测试重构后的唤醒模块。重构后的唤醒模块提供了两种使用方式：直接从麦克风捕获音频，或者接收外部程序提供的音频数据。

## 环境准备

### 依赖安装

在开始构建前，请确保安装了以下依赖：

```bash
# 安装ALSA开发库
sudo apt-get install libasound2-dev

# 安装SndFile库
sudo apt-get install libsndfile1-dev

# 安装nlohmann_json库
sudo apt-get install nlohmann-json3-dev
```

## 构建步骤

1. 进入项目目录：

```bash
cd xiaoniu_client/src/wake_up
```

2. 创建并进入构建目录：

```bash
mkdir -p build
cd build
```

3. 执行CMake配置：

```bash
cmake ..
```

4. 编译项目：

```bash
make
```

5. 安装（可选）：

```bash
sudo make install
```

## 测试指南

### 测试程序说明

重构后的唤醒模块提供了两个测试程序：

1. `test_microphone`：直接从麦克风捕获音频并进行唤醒检测
2. `test_external_audio`：模拟外部程序捕获音频，然后传递给唤醒模块进行检测

### 测试步骤

#### 测试1：直接从麦克风捕获

1. 运行测试程序：

```bash
./test_microphone
```

2. 对着麦克风说出唤醒词（例如"小牛小牛"或其他配置的唤醒词）

3. 观察程序输出，应该能看到唤醒词被正确检测的信息

4. 按下Ctrl+C结束测试

#### 测试2：外部音频流

1. 运行测试程序：

```bash
./test_external_audio
```

2. 对着麦克风说出唤醒词

3. 观察程序输出，应该能看到唤醒词被正确检测的信息

4. 按下Ctrl+C结束测试

### 常见问题排查

#### 麦克风未正确设置

如果测试程序无法捕获音频，请检查系统麦克风设置：

```bash
# 查看录音设备
arecord -l

# 测试麦克风
arecord -d 5 test.wav  # 录制5秒音频
aplay test.wav  # 播放录制的音频
```

确保系统默认麦克风工作正常。

#### 找不到动态库

如果运行测试程序时报错找不到动态库，可以设置LD_LIBRARY_PATH：

```bash
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib:/path/to/wake_up/libs
```

#### 无法检测到唤醒词

如果说出唤醒词后没有反应，请尝试：

1. 确认麦克风工作正常
2. 检查唤醒词配置是否正确（配置文件位于resource目录）
3. 适当调整音量和语速

## 开发者集成指南

### 作为共享库集成

1. 安装编译好的库文件和头文件

2. 在你的项目中包含头文件：

```cpp
#include <wake_up/wake_up_detector.h>
```

3. 链接库文件：

```
-lwake_up -lasound -lsndfile -lnlohmann_json
```

### 集成示例代码

```cpp
#include <wake_up/wake_up_detector.h>
#include <iostream>

void onWakeUp(const std::string& keyword, int confidence) {
    std::cout << "检测到唤醒词: " << keyword << std::endl;
    // 进行后续处理...
}

int main() {
    // 创建唤醒检测器
    WakeUpDetector detector;
    
    // 设置回调函数
    detector.setWakeUpCallback(onWakeUp);
    
    // 方法1：直接从麦克风启动
    detector.startWithMicrophone();
    
    // 或者
    // 方法2：处理外部音频数据
    // int16_t audio_buffer[1024];
    // ... 从其他源获取音频数据 ...
    // detector.processAudio(audio_buffer, 1024);
    
    // 等待用户输入以结束程序
    std::cout << "按Enter键结束程序..." << std::endl;
    std::cin.get();
    
    // 停止唤醒检测
    detector.stop();
    
    return 0;
}
``` 