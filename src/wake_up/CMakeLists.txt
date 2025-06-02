cmake_minimum_required(VERSION 3.5)
project(wake_up)

# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -g -fno-omit-frame-pointer)
endif()

# 禁止剥离符号，保留调试信息
# 如果不设置这些值：
# Release模式下程序会更小、可能略快，但无法有效调试
# 没有-rdynamic时，运行时将缺少完整的符号信息，导致崩溃时无法获得有用的堆栈跟踪，不利于问题诊断
# 这些设置对于需要在生产环境进行调试和诊断的应用程序非常有价值。
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -g")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -rdynamic")

## 查找包
# find_package(ament_cmake REQUIRED)
# find_package(rclcpp REQUIRED)
# find_package(wake_up REQUIRED)
# find_package(bridge REQUIRED)
# find_package(command_word REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(SNDFILE REQUIRED sndfile)
# pkg_check_modules(ALSA REQUIRED alsa)
## 查找Python包
# find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
# find_package(pybind11 REQUIRED)

# # 添加gperftools依赖
# pkg_check_modules(GPERFTOOLS REQUIRED libprofiler)
# pkg_check_modules(TCMALLOC REQUIRED libtcmalloc)


# # 链接Python库
# target_link_libraries(voice_recognition_lib
#     PRIVATE
#         pybind11::module
#         ${PYTHON3_LIBRARIES}
# )

# install(TARGETS voice_recognition
#   EXPORT voice_recognition
#   LIBRARY DESTINATION lib/${PROJECT_NAME}
# )

if(NOT TARGET_ARCH)
  if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64")
    set(TARGET_ARCH "arm64")
  else()
    set(TARGET_ARCH "amd64")
  endif()
endif()

set(RESOURCE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/resource/${TARGET_ARCH}")
set(PLATFORM_LIB_PATH "${CMAKE_CURRENT_SOURCE_DIR}/libs/${TARGET_ARCH}")


configure_file(
  ${CMAKE_CURRENT_SOURCE_DIR}/include/config.h.in 
  ${CMAKE_CURRENT_BINARY_DIR}/include/config.h
  @ONLY
)


include_directories(
  # ../voice_print/include
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_BINARY_DIR}/include
  ${SNDFILE_INCLUDE_DIRS}
  # ${ALSA_INCLUDE_DIRS}
  # ${Python3_INCLUDE_DIRS}
  # ${pybind11_INCLUDE_DIRS}
  ${CMAKE_CURRENT_SOURCE_DIR}/3rdparty/json/include
)

link_directories(
  # ${CMAKE_INSTALL_PREFIX}/../voice_print/lib
  ${PLATFORM_LIB_PATH}
  ${SNDFILE_LIBRARY_DIRS}
  # ${ALSA_LIBRARY_DIRS}
)

set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)
set(CMAKE_INSTALL_RPATH 
    # ${PLATFORM_LIB_PATH}   # 不需要，因为已经用了 link_directories
    ${CMAKE_INSTALL_PREFIX}/lib/${PROJECT_NAME}
)

# 设置静态库位置
set(AIKIT_STATIC_LIB "${PLATFORM_LIB_PATH}/libaikit.a")

# 生成共享库
add_library(${PROJECT_NAME} SHARED
  src/wake_up_detector.cpp
  src/ivw_wrapper.cpp
  src/audio_buffer.cpp
  src/speech_recognizer.cpp
  src/linuxrec.c
)

# 设置版本号和 soname
set_target_properties(${PROJECT_NAME} PROPERTIES
  VERSION 1.0.0
  SOVERSION 1
)

# 链接依赖库，静态链接 AIkit
target_link_libraries(${PROJECT_NAME}
  PRIVATE
    ${AIKIT_STATIC_LIB}  # 静态链接 AIkit
    ${ALSA_LIBRARIES}
    ${SNDFILE_LIBRARIES}
    nlohmann_json::nlohmann_json
    pthread
)

# 添加测试程序
add_executable(test_microphone tests/test_microphone.cpp)
target_link_libraries(test_microphone 
  PRIVATE
    ${PROJECT_NAME}
)

add_executable(test_external_audio tests/test_external_audio.cpp)
target_link_libraries(test_external_audio 
  PRIVATE
    ${PROJECT_NAME}
    ${ALSA_LIBRARIES}
)

# 安装目标
install(TARGETS ${PROJECT_NAME}
  LIBRARY DESTINATION lib
)

# 安装头文件（只安装公共API头文件）
install(DIRECTORY include/wake_up
  DESTINATION include
  FILES_MATCHING PATTERN "*.h"
)

# 安装测试程序
install(TARGETS test_microphone test_external_audio
  RUNTIME DESTINATION bin
)

# 安装测试操作文档
install(FILES 
  doc/test_guide.md 
  DESTINATION share/doc/${PROJECT_NAME}
)

# # 安装Python模块和相关文件
# install(
#   FILES 
#     voice_recognition/voice_recognition_wrapper.py
#     voice_recognition/__init__.py
#   DESTINATION lib/${PROJECT_NAME}/voice_recognition
# )

# install(DIRECTORY 
#   voice_recognition/configs
#   voice_recognition/models 
#   voice_recognition/audio_db
#   voice_recognition/mvector
#   DESTINATION lib/${PROJECT_NAME}/voice_recognition
# )


# # 添加Python相关信息
# message(STATUS "Python3_EXECUTABLE: ${Python3_EXECUTABLE}")
# message(STATUS "Python3_INCLUDE_DIRS: ${Python3_INCLUDE_DIRS}")
# message(STATUS "Python3_LIBRARIES: ${PYTHON3_LIBRARIES}")
# message(STATUS "RPATH is ${CMAKE_INSTALL_RPATH}")
# message(STATUS "=========================")



#introspect
message(STATUS "CMAKE_INSTALL_PREFIX: ${CMAKE_INSTALL_PREFIX}")
message(STATUS "TARGET_ARCH: ${TARGET_ARCH}")
message(STATUS "RESOURCE_PATH: ${RESOURCE_PATH}")
message(STATUS "PLATFORM_LIB_PATH: ${PLATFORM_LIB_PATH}")

