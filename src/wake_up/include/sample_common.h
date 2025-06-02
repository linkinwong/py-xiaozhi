#ifndef SAMPLE_COMMON_H
#define SAMPLE_COMMON_H

#include <fstream>
#include <assert.h>
#include <cstring>
#include <atomic>
#include <unistd.h>

#if ENABLE_AIKIT
#include "../include/aikit_biz_api.h"
#include "../include/aikit_constant.h"
#include "../include/aikit_biz_config.h"

using namespace std;
using namespace AIKIT;

// static const char *AISOUND_ABILITY = "ece9d3c90";
// static const char *XTTS_ABILITY = "e2e44feff";
static const char *IVW_ABILITY = "e867a88f2";
static const char *ESR_ABILITY = "e75f07b62";
extern FILE *fin;
extern std::atomic_bool ttsFinished;
#else
// 提供简单的存根定义，以便在没有 AIKIT 时编译
typedef void AIKIT_HANDLE;
typedef void AIKIT_EVENT;
typedef void AIKIT_OutputEvent;
typedef void AIKIT_OutputData;
typedef void AIKIT_InputData;
typedef void AIKIT_BaseData;
typedef void AIKIT_Callbacks;

#define IVW_ABILITY "e867a88f2"
#define ESR_ABILITY "e75f07b62"
#define AIKIT_DATA_PTR_PATH 1
#define LOG_LVL_INFO 2

extern std::atomic_bool ttsFinished;
#endif

// void TestAisound(const AIKIT_Callbacks& cbs);
// void TestXtts(const AIKIT_Callbacks &cbs);

#if ENABLE_AIKIT
// 原始声明
void TestIvw70(const AIKIT_Callbacks& cbs);
void TestESR(const AIKIT_Callbacks& cbs);
#else
// 在 AIKIT 禁用时使用 void* 替代引用
void TestIvw70(const void* cbs);
void TestESR(const void* cbs);
#endif

#endif
