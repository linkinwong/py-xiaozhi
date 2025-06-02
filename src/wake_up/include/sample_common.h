#ifndef SAMPLE_COMMON_H
#define SAMPLE_COMMON_H

#include <fstream>
#include <assert.h>
#include <cstring>
#include <atomic>
#include <unistd.h>

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

// void TestAisound(const AIKIT_Callbacks& cbs);
// void TestXtts(const AIKIT_Callbacks &cbs);


void TestIvw70(const AIKIT_Callbacks& cbs);
void TestESR(const AIKIT_Callbacks& cbs);



#endif
