/* Offline, bounded MP3 to PCM WAV helper. minimp3 is CC0 (vendor/minimp3). */
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_SIMD
#include "vendor/minimp3/minimp3_ex.h"
#include <stdint.h>
#include <stdio.h>
static void le16(FILE *f, unsigned n) { fputc(n&255,f);fputc((n>>8)&255,f); }
static void le32(FILE *f, unsigned n) { le16(f,n&65535);le16(f,n>>16); }
static void header(FILE *f, unsigned frames, unsigned hz, unsigned channels) {
    unsigned bytes=frames*channels*2;
    rewind(f);fwrite("RIFF",1,4,f);le32(f,bytes+36);fwrite("WAVEfmt ",1,8,f);le32(f,16);
    le16(f,1);le16(f,channels);le32(f,hz);le32(f,hz*channels*2);le16(f,channels*2);le16(f,16);
    fwrite("data",1,4,f);le32(f,bytes);
}
int main(int argc,char **argv) {
    mp3dec_ex_t decoder;mp3d_sample_t pcm[8192];size_t got,total=0;int rate,channels;
    if(argc!=3)return 2;
    if(mp3dec_ex_open(&decoder,argv[1],MP3D_DO_NOT_SCAN))return 3;
    FILE *out=fopen(argv[2],"wb");if(!out){mp3dec_ex_close(&decoder);return 4;}
    got=mp3dec_ex_read(&decoder,pcm,8192);rate=decoder.info.hz;channels=decoder.info.channels;
    if(rate<8000||rate>48000||channels<1||channels>2){fclose(out);mp3dec_ex_close(&decoder);return 5;}
    header(out,0,(unsigned)rate,(unsigned)channels);
    while(got){
        if(total+got>(size_t)rate*channels*1800||decoder.info.hz!=rate||decoder.info.channels!=channels){fclose(out);mp3dec_ex_close(&decoder);return 6;}
        if(fwrite(pcm,sizeof(*pcm),got,out)!=got){fclose(out);mp3dec_ex_close(&decoder);return 7;}
        total+=got;got=mp3dec_ex_read(&decoder,pcm,8192);
    }
    int error=decoder.last_error;
    header(out,(unsigned)(total/channels),(unsigned)rate,(unsigned)channels);fclose(out);mp3dec_ex_close(&decoder);
    return error?8:0;
}
