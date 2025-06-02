# 下一步操作指南

我们已经完成了唤醒模块的重构设计和代码实现，但在实际构建和测试过程中发现一些依赖问题。本文档提供完成剩余工作的指南。

## 依赖问题解决

在构建过程中，我们遇到了以下依赖问题：

1. **nlohmann_json**: 找不到nlohmann_json包配置文件
2. **ALSA和SndFile**: 可能在某些系统上也需要安装

### 解决方案

1. **安装nlohmann_json**:

```bash
# Ubuntu/Debian
sudo apt-get install nlohmann-json3-dev

# macOS
brew install nlohmann-json

# 如果无法安装包，可以直接包含头文件
# 下载头文件: https://github.com/nlohmann/json/releases
# 然后修改CMakeLists.txt，直接包含头文件路径
```

2. **修改CMakeLists.txt**，增加更灵活的依赖处理：

```cmake
# 尝试查找系统安装的nlohmann_json
find_package(nlohmann_json QUIET)

# 如果找不到，使用捆绑的版本或者直接包含头文件
if(NOT nlohmann_json_FOUND)
  message(STATUS "System nlohmann_json not found, using bundled version")
  include_directories(${CMAKE_CURRENT_SOURCE_DIR}/3rdparty/json/include)
endif()
```

## 后续测试步骤

一旦解决依赖问题，请按照以下步骤完成测试：

1. **重新构建项目**:

```bash
cd build
cmake ..
make
```

2. **运行测试程序**:

```bash
# 测试直接从麦克风捕获
./test_microphone

# 测试外部音频流
./test_external_audio
```

3. **验证功能**:
   - 对着麦克风说唤醒词
   - 确认程序输出中显示检测到唤醒词
   - 测试停止功能和资源释放

## 集成指南

重构后的唤醒模块可以通过以下方式集成到其他应用中：

### 方法1：直接链接

1. 安装编译好的库和头文件
2. 在CMake项目中使用：

```cmake
find_package(wake_up REQUIRED)
target_link_libraries(your_application PRIVATE wake_up)
```

3. 或者在Makefile中使用：

```
CXXFLAGS += -I/path/to/wake_up/include
LDFLAGS += -L/path/to/wake_up/lib -lwake_up -lasound -lsndfile
```

### 方法2：包含源代码

对于更紧密的集成，可以直接将源代码包含到项目中：

1. 将`include`和`src`目录复制到你的项目中
2. 添加到你的构建系统

## 未来改进

在完成基本功能测试后，建议进行以下改进：

1. **更好的错误处理**：增加更详细的错误信息和错误恢复机制
2. **配置选项**：提供更多配置选项，如设备选择、灵敏度调整等
3. **资源管理**：优化资源使用，减少内存占用
4. **跨平台支持**：改进对Windows和macOS的支持
5. **文档完善**：编写详细的API文档和使用示例

## 测试数据收集

为了确保重构后的功能与原有功能一致，建议收集以下测试数据：

1. **唤醒率**：在不同环境下的唤醒成功率
2. **误触发率**：记录误触发的频率
3. **资源占用**：监控CPU和内存使用情况
4. **延迟时间**：从说出唤醒词到触发回调的时间

## 结论

虽然我们无法在当前环境中完成实际构建和测试，但重构设计和代码实现已经完成。解决上述依赖问题后，重构后的唤醒模块应该能够满足需求，提供一个独立的、易于集成的唤醒检测功能。 