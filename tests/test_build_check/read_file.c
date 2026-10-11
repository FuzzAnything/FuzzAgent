#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdlib.h>

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
{
    if (size < (size_t) 8)
        return -1;
    char *crash = NULL;
    if (data[0] == 'f')
        if (data[1] == 'u')
            if (data[2] == 'z')
                if (data[3] == 'z')
                    if (data[4] == 'A')
                        if (data[5] == 'g')
                            if (data[6] == 'e')
                                if (data[7] == 'n')
                                    if (data[8] == 't')
                                    {
                                        *crash = '1';
                                        abort();
                                    }
    return 1;
}

int main(int argc, char **argv)
{
    FILE *f;
    char *buf = NULL;
    long siz_buf;

    if(argc < 2)
    {
        fprintf(stderr, "no input file\n");
        goto err;
    }

    f = fopen(argv[1], "rb");
    if(f == NULL)
    {
        fprintf(stderr, "error opening input file %s\n", argv[1]);
        goto err;
    }

    fseek(f, 0, SEEK_END);

    siz_buf = ftell(f);
    rewind(f);

    if(siz_buf < 1) goto err;

    buf = (char*)malloc((size_t)siz_buf);
    if(buf == NULL)
    {
        fprintf(stderr, "malloc() failed\n");
        goto err;
    }

    if(fread(buf, (size_t)siz_buf, 1, f) != 1)
    {
        fprintf(stderr, "fread() failed\n");
        goto err;
    }
    (void) LLVMFuzzerTestOneInput(buf, siz_buf);

err:
    free(buf);
    return 0;
}