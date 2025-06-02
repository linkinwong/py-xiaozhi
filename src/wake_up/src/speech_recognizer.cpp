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

using namespace AIKIT;

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

		AIKIT_End(sr->handle);
		sr->handle = NULL;
	}
	sr->state = SR_STATE_INIT;
}

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
	AIKIT_ParamBuilder* paramBuilder = nullptr;

	if (aud_src == SR_MIC && get_input_dev_num() == 0) {
		return -E_SR_NOACTIVEDEVICE;
	}

	if (!sr)
		return -E_SR_INVAL;

	SR_MEMSET(sr, 0, sizeof(struct speech_rec));
	sr->state = SR_STATE_INIT;
	sr->aud_src = aud_src;
	sr->audio_status = AIKIT_DataBegin;
	sr->ABILITY = ability_id;
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

		paramBuilder->clear();
		paramBuilder->param("languageType", 0);
		paramBuilder->param("vadEndGap", 75);
		paramBuilder->param("vadOn", true);
		paramBuilder->param("beamThreshold", 20);
		paramBuilder->param("hisGramThreshold", 3000);
		paramBuilder->param("postprocOn", true);
		paramBuilder->param("vadResponsetime", 1000);
		paramBuilder->param("vadLinkOn", true);
		paramBuilder->param("vadSpeechEnd", 80);
	}
	
	errcode = AIKIT_Start(sr->ABILITY, AIKIT_Builder::build(paramBuilder), nullptr, &sr->handle);
	if (0 != errcode)
	{
		sr_dbg("\nAIKIT_Start failed! error code:%d\n", errcode);
		return errcode;
	}
	
	if (aud_src == SR_MIC) {
		errcode = create_recorder(&sr->recorder, record_cb, (void*)sr);
		if (sr->recorder == NULL || errcode != 0) {
			sr_dbg("create recorder failed: %d\n", errcode);
			errcode = -E_SR_RECORDFAIL;
			goto fail;
		}
		//音频采样率
		wavfmt.nSamplesPerSec = 16000;
		wavfmt.nAvgBytesPerSec = wavfmt.nBlockAlign * wavfmt.nSamplesPerSec;
	
		errcode = open_recorder(sr->recorder, devid, &wavfmt);
		if (errcode != 0) {
			sr_dbg("recorder open failed: %d\n", errcode);
			errcode = -E_SR_RECORDFAIL;
			goto fail;
		}
	}

	if(paramBuilder != nullptr)
	{
		delete paramBuilder;
		paramBuilder = nullptr;
	}

	return 0;

fail:
	if (sr->recorder) {
		destroy_recorder(sr->recorder);
		sr->recorder = NULL;
	}

	
	SR_MEMSET(&sr->notif, 0, sizeof(sr->notif));

	return errcode;
}

/* use the default input device to capture the audio. see sr_init_ex */
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

	
	sr->audio_status = AIKIT_DataBegin;

	if (sr->aud_src == SR_MIC) {
		ret = start_record(sr->recorder);
		if (ret != 0) {
			sr_dbg("start record failed: %d\n", ret);
			ret = AIKIT_End(sr->handle);
			sr->handle = NULL;
			return -E_SR_RECORDFAIL;
		}
	}

	sr->state = SR_STATE_STARTED;

	printf("Start Listening...\n");

	return 0;
}

/* after stop_record, there are still some data callbacks */
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
	AiAudio* aiAudio_raw = NULL;

	if (sr->state < SR_STATE_STARTED) {
		//sr_dbg("Not started or already stopped.\n");
		return 0;
	}

	if (sr->aud_src == SR_MIC) {
		ret = stop_record(sr->recorder);
		if (ret != 0) {
			sr_dbg("Stop failed! \n");
			return -E_SR_RECORDFAIL;
		}
		wait_for_rec_stop(sr->recorder, (unsigned int)-1);
	}
	sr->state = SR_STATE_INIT;
	if(!strcmp(sr->ABILITY,ESR_ABILITY))
	{
		sr->dataBuilder->clear();
		aiAudio_raw = AiAudio::get("audio")->data(NULL, 0)->status(AIKIT_DataEnd)->valid();
		sr->dataBuilder->payload(aiAudio_raw);

		ret = ESRGetRlt(sr->handle, sr->dataBuilder);
		if (ret != 0)
		{
			sr_dbg("write LAST_SAMPLE failed %d\n", ret);
			AIKIT_End(sr->handle);
			return ret;
		}
	}

	AIKIT_End(sr->handle);
	sr->handle = NULL;
	return 0;
}
int write_count = 0;
int sr_write_audio_data(struct speech_rec *sr, char *data, unsigned int len)
{
	sr_dbg("sr_write_audio_data %d\n",write_count++);

	AiAudio* aiAudio_raw = NULL;
	int ret = 0;
	if (!sr )
		return -E_SR_INVAL;
	if (!data || !len)
		return 0;
	
	sr->dataBuilder->clear();
	if(!strcmp(sr->ABILITY,ESR_ABILITY))
	{
		aiAudio_raw = AiAudio::get("audio")->data(data, len)->status(sr->audio_status)->valid();
		sr->dataBuilder->payload(aiAudio_raw);

		ret = ESRGetRlt(sr->handle, sr->dataBuilder);
		sr->audio_status = AIKIT_DataContinue;
	}
	else if(!strcmp(sr->ABILITY,IVW_ABILITY))
	{
		aiAudio_raw = AiAudio::get("wav")->data(data, len)->valid();
		sr->dataBuilder->payload(aiAudio_raw);
		ret = AIKIT_Write(sr->handle, AIKIT_Builder::build(sr->dataBuilder));
	}
	if (ret)
	{
		end_sr_on_error(sr, ret);
		return ret;
	}

	return 0;
}

void sr_uninit(struct speech_rec * sr)
{
	if (sr->recorder) {
		if(!is_record_stopped(sr->recorder))
			stop_record(sr->recorder);
		close_recorder(sr->recorder);
		destroy_recorder(sr->recorder);
		sr->recorder = NULL;
	}

	if (sr->dataBuilder != nullptr) {
		delete sr->dataBuilder;
		sr->dataBuilder = nullptr;
	}

}

void sr_set_audio_callback(struct speech_rec *sr, audio_callback_t cb) {
	if (sr) {
		sr->audio_cb = cb;
	}
}
