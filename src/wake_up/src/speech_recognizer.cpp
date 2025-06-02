/*
@file
@brief a simple demo to recognize speech from microphone

@author		taozhang9
@date		2016/05/27
*/

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include "speech_recognizer.h"
#include "sample_common.h"

#if ENABLE_AIKIT
using namespace AIKIT;
#endif

#define SR_DBGON 0
#if SR_DBGON == 1
#	define sr_dbg printf
#else
#	define sr_dbg(...) (void)0
#endif

#define DEFAULT_FORMAT		\
{\
	WAVE_FORMAT_PCM,	\
	1,			\
	16000,			\
	32000,			\
	2,			\
	16,			\
	sizeof(WAVEFORMATEX)	\
}

/* internal state */
enum {
	SR_STATE_INIT,
	SR_STATE_STARTED
};


#define SR_MALLOC malloc
#define SR_MFREE  free
#define SR_MEMSET	memset


static void Sleep(size_t ms)
{
	usleep(ms*1000);
}
bool is_result = false;

static void end_sr_on_error(struct speech_rec *sr, int errcode)
{
	if(sr->aud_src == SR_MIC)
		stop_record(sr->recorder);
	
	if (sr->handle) {
		if (sr->notif.on_speech_end)
			sr->notif.on_speech_end(errcode);

#if ENABLE_AIKIT
		AIKIT_End(sr->handle);
#endif
		sr->handle = NULL;
	}
	sr->state = SR_STATE_INIT;
}

#if ENABLE_AIKIT
int ESRGetRlt(AIKIT_HANDLE *handle,AIKIT_DataBuilder *dataBuilder)
{
    int ret = 0;
	
    AIKIT_OutputData *output = nullptr;
    AIKIT_InputData *input_data = AIKIT_Builder::build(dataBuilder);
    ret = AIKIT_Write(handle, input_data);
    if (ret != 0)
    {
        printf("AIKIT_Write:%d\n", ret);
        return ret;
    }
    ret = AIKIT_Read(handle, &output);
    if (ret != 0)
    {
        printf("AIKIT_Read:%d\n", ret);
        return ret;
    }
	
    if (output != nullptr)
    {
		FILE *fin = fopen("esr_result.txt", "ab");
		if (fin == nullptr)
		{
			printf("文件打开失败！");
			return -1;
		}
		AIKIT_BaseData *node = output->node;
		while (node != nullptr && node->value != nullptr)
        {
            fwrite(node->key, sizeof(char), strlen(node->key), fin);
            fwrite(": ", sizeof(char), strlen(": "), fin);
            fwrite(node->value, sizeof(char), node->len, fin);
            fwrite("\n", sizeof(char), strlen("\n"), fin);
            printf("key:%s\tvalue:%s\n", node->key, (char *)node->value);
			if(node->status == 2)
				is_result = true;
			node = node->next;
        }
		fclose(fin);
    }

	if(is_result)
	{
		is_result = false;
		return ESR_RESULT_END;
	}

    return ret;
}
#else
// 存根实现
int ESRGetRlt(AIKIT_HANDLE *handle, void *dataBuilder)
{
    return 0;
}
#endif

/* the record call back */
static void record_cb(char *data, unsigned long len, void *user_para)
{
	int errcode;
	struct speech_rec *sr;

	if(len == 0 || data == NULL)
		return;

	sr = (struct speech_rec *)user_para;

	if(sr == NULL)
		return;
        
	// 调用音频回调
	if (sr->audio_cb) {
		sr->audio_cb((const int16_t*)data, len/2);
	}
	
	if (sr->state < SR_STATE_STARTED)
		return; /* ignore the data if error/vad happened */
	
	errcode = sr_write_audio_data(sr, data, len);
	if (errcode) {
		end_sr_on_error(sr, errcode);
		return;
	}
}


/* devid will be ignored if aud_src is not SR_MIC ; use get_default_dev_id
 * to use the default input device. Currently the device list function is
 * not provided yet. 
 */

int sr_init_ex(struct speech_rec * sr, int count, const char* ability_id, enum sr_audsrc aud_src, record_dev_id devid)
{
	int errcode = 0;
	WAVEFORMATEX wavfmt = DEFAULT_FORMAT;

	if (aud_src == SR_MIC && get_input_dev_num() == 0) {
		return -E_SR_NOACTIVEDEVICE;
	}

	if (!sr)
		return -E_SR_INVAL;

	SR_MEMSET(sr, 0, sizeof(struct speech_rec));
	sr->state = SR_STATE_INIT;
	sr->aud_src = aud_src;
	sr->audio_status = 0; // 修改为简单的状态值，之前是AIKIT_DataBegin
	sr->ABILITY = ability_id;
	
#if ENABLE_AIKIT
	AIKIT_ParamBuilder* paramBuilder = nullptr;
	sr->dataBuilder = nullptr;
	sr->dataBuilder = AIKIT_DataBuilder::create();
	paramBuilder = AIKIT_ParamBuilder::create();

	int *index = nullptr;
	index = (int *)malloc(count * sizeof(int));
	for (int i = 0; i < count; ++i)
		index[i] = i;

	if(!strcmp(ability_id, IVW_ABILITY))
	{
		errcode = AIKIT_SpecifyDataSet(sr->ABILITY, "key_word", index, count);
		printf("AIKIT_SpecifyDataSet:%d\n", errcode);
		if (errcode != 0)
		{
			free(index);
			return errcode;
		}
		free(index);

		paramBuilder->param("wdec_param_nCmThreshold", "0 0:1000", strlen("0 0:1000"));
		paramBuilder->param("gramLoad", true);
	}
	else if(!strcmp(ability_id, ESR_ABILITY))
	{
		errcode = AIKIT_SpecifyDataSet(sr->ABILITY, "FSA", index, count);
		printf("AIKIT_SpecifyDataSet:%d\n", errcode);
		if (errcode != 0)
		{
			free(index);
			return errcode;
		}
		free(index);

		paramBuilder->param("nbest", 1);
		paramBuilder->param("audio_enc", "speex");
		paramBuilder->param("need_partial_result", "false");
		paramBuilder->param("need_audio", "true");
		paramBuilder->param("debug_set", 0);
	}

	// 设置状态为初始化完成
	// 创建引擎实例
	AIKIT_CreateParam param;
	param.nChannels = 1;
	param.sampleRate = 16000;
	param.bitsPerSample = 16;
	param.param = AIKIT_Builder::build(paramBuilder);

	errcode = AIKIT_Create(&sr->handle, sr->ABILITY, &param);
	printf("AIKIT_Create:%d\n", errcode);
	if (errcode != 0)
	{
		return errcode;
	}

	AIKIT_Builder::destroy(param.param);
	paramBuilder->destroy();

#else
	// 存根实现
	printf("使用模拟语音识别器 (没有AIKIT支持)\n");
#endif

	if (aud_src == SR_MIC) {
		record_dev_id devid = get_default_input_dev();
		if ((errcode = create_recorder(&sr->recorder, record_cb, sr)) != 0) {
			sr->recorder = NULL;
			return errcode;
		}

		if ((errcode = open_recorder(sr->recorder, devid, &wavfmt)) != 0) {
			if (sr->recorder) {
				destroy_recorder(sr->recorder);
				sr->recorder = NULL;
			}
			return errcode;
		}
	}

	return 0;
}

int sr_init(struct speech_rec * sr, int count, const char* ability_id, enum sr_audsrc aud_src)
{
	return sr_init_ex(sr, count, ability_id, aud_src, get_default_input_dev());
}

int sr_start_listening(struct speech_rec *sr)
{
	int ret = 0;
	if (sr->state >= SR_STATE_STARTED) {
		sr_dbg("already STARTED.\n");
		return -E_SR_ALREADY;
	}

	if (sr->aud_src == SR_MIC) {
		ret = start_record(sr->recorder);
		if (ret != 0) {
			sr_dbg("error start record.\n");
			return -E_SR_RECORDFAIL;
		}
	}

	sr->state = SR_STATE_STARTED;

	return 0;
}

/* 仅用于内部 */
static void wait_for_rec_stop(struct recorder *rec, unsigned int timeout_ms)
{
	while (!is_record_stopped(rec)) {
		Sleep(1);
		if (timeout_ms != (unsigned int)-1)
			if (0 == timeout_ms--)
				break;
	}
}

int sr_stop_listening(struct speech_rec *sr)
{
	int ret = 0;
	const unsigned int max_silence_timeout = 60*1000;

	if (sr->state < SR_STATE_STARTED) {
		sr_dbg("Not started or already stopped.\n");
		return 0;
	}

	if (sr->aud_src == SR_MIC) {
		ret = stop_record(sr->recorder);
		if (ret != 0) {
			sr_dbg("error stop record.\n");
			return -E_SR_RECORDFAIL;
		}
		wait_for_rec_stop(sr->recorder, max_silence_timeout);
	}
	sr->state = SR_STATE_INIT;
	return 0;
}

int sr_write_audio_data(struct speech_rec *sr, char *data, unsigned int len)
{
	const char *pcm = data;
	int ret = 0;
	int have_remain = 1;
	int data_pos = 0;
	int pcm_size = len;
	static int audio_status = 0;

	while (1) {
#if ENABLE_AIKIT
		// 如果没有剩余数据，则中断循环
		if (data_pos >= pcm_size)
			break;

		// 准备音频数据
		sr->dataBuilder->audio(pcm + data_pos, pcm_size - data_pos, audio_status, 16000, 1, 16);
		data_pos = pcm_size;

		// 写入音频并获取结果
		int ret = ESRGetRlt(sr->handle, sr->dataBuilder);
		if(ret != 0 && ret != ESR_RESULT_END)
		{
			printf("ESRGetRlt Error:%d\n", ret);
			break;
		}

		// 首次发送音频后，状态改为 DataContinue
		if(audio_status == 0) {
			audio_status = 1;
		}

		// 如果没有剩余数据，则中断循环
		if (!have_remain)
			break;
#else
		// 存根实现 - 仅记录有音频写入
		printf("音频数据写入: %d 字节\n", len);
		break;
#endif
	}

	return ret;
}

void sr_uninit(struct speech_rec * sr)
{
	if (!sr)
		return;

	if (sr->recorder) {
		if (!is_record_stopped(sr->recorder))
			stop_record(sr->recorder);
		close_recorder(sr->recorder);
		destroy_recorder(sr->recorder);
		sr->recorder = NULL;
	}

#if ENABLE_AIKIT
	if (sr->handle) {
		AIKIT_End(sr->handle);
		AIKIT_Destroy(sr->handle);
		sr->handle = NULL;
	}

	if (sr->dataBuilder)
	{
		sr->dataBuilder->destroy();
		sr->dataBuilder = nullptr;
	}
#endif
}

void sr_set_audio_callback(struct speech_rec *sr, audio_callback_t cb) {
    if (sr) {
        sr->audio_cb = cb;
    }
}
