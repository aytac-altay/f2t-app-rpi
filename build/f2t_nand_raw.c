/*
 * f2t_nand_raw.c  -  Raspberry Pi için Paralel NAND Programlama Aracı (Genel Amaçlı)
 *
 * rpi-raw-nand-v3'ün GPIO performansı + Python betiğinin JSON veritabanı ve menüsü
 *
 * GPIO eşleşmesi:
 *   WP# : GPIO 2
 *   R/B#: GPIO 3  (dahili pull-up)
 *   ALE : GPIO 4
 *   CLE : GPIO 5
 *   RE# : GPIO 6
 *   WE# : GPIO 7
 *   I/O0-7: GPIO 8-15
 *   CE# : GND'ye bağlı (sürekli aktif)
 *
 * Derleme:
 *   gcc -O2 -Wall -o f2t_nand_raw f2t_nand_raw.c cJSON.c -lm
 *
 * Çalıştırma:
 *   sudo ./f2t_nand_raw
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <time.h>
#include <stdint.h>
#include "cJSON.h"

/* ================================================================ *
 *  Dinamik NAND parametreleri (JSON'dan yüklenir)                   *
 * ================================================================ */
typedef struct {
    char model[64];
    int data_size;          // yalnızca veri alanı (byte), örn. 2048
    int oob_size;           // yedek alan (byte), örn. 128
    int pages_per_block;    // blok başına sayfa sayısı
    int total_blocks;       // toplam blok sayısı
} NandChipInfo;

NandChipInfo chip;

/* Toplam sayfa boyutu (veri + OOB) */
static inline int page_total(void) {
    return chip.data_size + chip.oob_size;
}

/* ================================================================ *
 *  GPIO yapılandırması                                              *
 * ================================================================ */
#define BCM_PERI_BASE    0x3F000000
#define GPIO_BASE        (BCM_PERI_BASE + 0x200000)

#define GPFSEL           0
#define GPSET            7
#define GPCLR            10
#define GPLEV            13
#define GPPUD            37
#define GPPUDCLK         38

#define PIN_WP           2
#define PIN_RB           3
#define PIN_ALE          4
#define PIN_CLE          5
#define PIN_RE           6
#define PIN_WE           7

int data_pins[8] = { 8, 9, 10, 11, 12, 13, 14, 15 };
volatile uint32_t *gpio;
int delay_us = 50;

/* ================================================================ *
 *  GPIO düşük seviye işlemleri                                      *
 * ================================================================ */
void INP_GPIO(int g) {
    gpio[GPFSEL + g/10] &= ~(7 << ((g%10)*3));
}
void OUT_GPIO(int g) {
    INP_GPIO(g);
    gpio[GPFSEL + g/10] |= (1 << ((g%10)*3));
}
void SET_GPIO(int g) { gpio[GPSET] = 1 << g; }
void CLR_GPIO(int g) { gpio[GPCLR] = 1 << g; }
int READ_GPIO(int g) { return (gpio[GPLEV] >> g) & 1; }

void gpio_pull_up(int pin) {
    gpio[GPPUD] = 2;
    usleep(5);
    gpio[GPPUDCLK] = (1 << pin);
    usleep(5);
    gpio[GPPUD] = 0;
    gpio[GPPUDCLK] = 0;
}

void shortpause(void) {
    volatile int i;
    for (i = 0; i < delay_us; i++) {
        asm volatile("nop");
    }
}

void data_in(void) {
    for (int i = 0; i < 8; i++) INP_GPIO(data_pins[i]);
}
void data_out(void) {
    for (int i = 0; i < 8; i++) OUT_GPIO(data_pins[i]);
}

void write_byte(uint8_t byte) {
    for (int i = 0; i < 8; i++) {
        if (byte & 1) SET_GPIO(data_pins[i]);
        else          CLR_GPIO(data_pins[i]);
        byte >>= 1;
    }
}

uint8_t read_byte(void) {
    uint8_t byte = 0;
    for (int i = 7; i >= 0; i--) {
        byte = (byte << 1) | READ_GPIO(data_pins[i]);
    }
    return byte;
}

/* ================================================================ *
 *  NAND temel komutları                                             *
 * ================================================================ */
void nand_command(uint8_t cmd) {
    SET_GPIO(PIN_CLE);
    CLR_GPIO(PIN_ALE);
    data_out();
    write_byte(cmd);
    CLR_GPIO(PIN_WE); shortpause();
    SET_GPIO(PIN_WE); shortpause();
    CLR_GPIO(PIN_CLE);
}

void nand_address(const uint8_t *addr, int len) {
    CLR_GPIO(PIN_CLE);
    SET_GPIO(PIN_ALE);
    data_out();
    for (int i = 0; i < len; i++) {
        write_byte(addr[i]);
        CLR_GPIO(PIN_WE); shortpause();
        SET_GPIO(PIN_WE); shortpause();
    }
    CLR_GPIO(PIN_ALE);
}

void nand_wait_busy(void) {
    while (READ_GPIO(PIN_RB) == 0)
        shortpause();
}

uint8_t nand_read_status(void) {
    nand_command(0x70);
    data_in();
    CLR_GPIO(PIN_RE); shortpause();
    uint8_t st = read_byte();
    SET_GPIO(PIN_RE); shortpause();
    return st & 0x01;
}

void nand_read_id(uint8_t id[5]) {
    nand_command(0x90);
    uint8_t addr = 0x00;
    nand_address(&addr, 1);
    data_in();
    for (int i = 0; i < 5; i++) {
        CLR_GPIO(PIN_RE); shortpause();
        id[i] = read_byte();
        SET_GPIO(PIN_RE); shortpause();
    }
}

int nand_read_page(int page, uint8_t *buf, int include_oob) {
    int len = include_oob ? page_total() : chip.data_size;
    uint8_t addr[5];
    addr[0] = 0;
    addr[1] = 0;
    addr[2] = page & 0xFF;
    addr[3] = (page >> 8) & 0xFF;
    addr[4] = (page >> 16) & 0xFF;
    nand_command(0x00);
    nand_address(addr, 5);
    nand_command(0x30);
    nand_wait_busy();
    data_in();
    for (int i = 0; i < len; i++) {
        CLR_GPIO(PIN_RE); shortpause();
        buf[i] = read_byte();
        SET_GPIO(PIN_RE); shortpause();
    }
    return 0;
}

int nand_write_page(int page, const uint8_t *buf, int include_oob) {
    int len = include_oob ? page_total() : chip.data_size;
    uint8_t addr[5];
    addr[0] = 0;
    addr[1] = 0;
    addr[2] = page & 0xFF;
    addr[3] = (page >> 8) & 0xFF;
    addr[4] = (page >> 16) & 0xFF;
    nand_command(0x80);
    nand_address(addr, 5);
    data_out();
    for (int i = 0; i < len; i++) {
        write_byte(buf[i]);
        CLR_GPIO(PIN_WE); shortpause();
        SET_GPIO(PIN_WE); shortpause();
    }
    nand_command(0x10);
    nand_wait_busy();
    if (nand_read_status()) {
        fprintf(stderr, "  [!] Program hatasi (sayfa %d)\n", page);
        return -1;
    }
    return 0;
}

int nand_erase_block(int block) {
    int page = block * chip.pages_per_block;
    uint8_t addr[3];
    addr[0] = page & 0xFF;
    addr[1] = (page >> 8) & 0xFF;
    addr[2] = (page >> 16) & 0xFF;
    nand_command(0x60);
    nand_address(addr, 3);
    nand_command(0xD0);
    nand_wait_busy();
    if (nand_read_status()) {
        fprintf(stderr, "  [!] Silme hatasi (blok %d)\n", block);
        return -1;
    }
    return 0;
}

/* ================================================================ *
 *  JSON veritabanı işlemleri (cJSON)                                *
 * ================================================================ */
#define DB_FILENAME "nand_paralel.json"

cJSON *load_db(void) {
    FILE *f = fopen(DB_FILENAME, "r");
    if (!f) {
        cJSON *db = cJSON_CreateObject();
        cJSON_AddItemToObject(db, "nand", cJSON_CreateObject());
        char *js = cJSON_Print(db);
        f = fopen(DB_FILENAME, "w");
        if (f) { fprintf(f, "%s", js); fclose(f); }
        free(js);
        printf("[*] Yeni bos veritabani olusturuldu.\n");
        return db;
    }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    rewind(f);
    char *data = malloc(sz + 1);
    fread(data, 1, sz, f);
    data[sz] = '\0';
    fclose(f);
    cJSON *db = cJSON_Parse(data);
    free(data);
    if (!db) {
        fprintf(stderr, "[!] Veritabani bozuk, yedekleniyor...\n");
        rename(DB_FILENAME, DB_FILENAME ".bak");
        db = cJSON_CreateObject();
        cJSON_AddItemToObject(db, "nand", cJSON_CreateObject());
    }
    return db;
}

void save_db(cJSON *db) {
    char *js = cJSON_Print(db);
    FILE *f = fopen(DB_FILENAME, "w");
    if (f) { fprintf(f, "%s", js); fclose(f); }
    free(js);
}

int load_chip_from_db(const char *chip_id_str) {
    cJSON *db = load_db();
    cJSON *nand = cJSON_GetObjectItem(db, "nand");
    if (!nand) { cJSON_Delete(db); return 0; }
    cJSON *entry = cJSON_GetObjectItem(nand, chip_id_str);
    if (!entry) { cJSON_Delete(db); return 0; }
    cJSON *model = cJSON_GetObjectItem(entry, "model");
    cJSON *ps    = cJSON_GetObjectItem(entry, "page_size");   // JSON'da yalnız veri boyutu
    cJSON *oob   = cJSON_GetObjectItem(entry, "oob_size");
    cJSON *bs_kb = cJSON_GetObjectItem(entry, "block_size_kb");
    cJSON *tb    = cJSON_GetObjectItem(entry, "total_blocks");
    if (model && ps && oob && bs_kb && tb) {
        strncpy(chip.model, model->valuestring, 63);
        chip.data_size = ps->valueint;
        chip.oob_size  = oob->valueint;
        // Sayfa başına blok = bloktaki veri boyutu / sayfa veri boyutu
        chip.pages_per_block = (bs_kb->valueint * 1024) / chip.data_size;
        chip.total_blocks = tb->valueint;
        cJSON_Delete(db);
        return 1;
    }
    cJSON_Delete(db);
    return 0;
}

void add_chip_to_db(const char *chip_id_str) {
    printf("[!] %s ID'li cip veritabaninda bulunamadi.\n", chip_id_str);
    printf("Lutfen asagidaki bilgileri girin (sayisal degerler):\n");
    char model[64];
    printf("Model adi: ");
    fgets(model, sizeof(model), stdin);
    model[strcspn(model, "\n")] = 0;
    printf("Sayfa veri boyutu (byte, orn: 2048): ");
    scanf("%d", &chip.data_size);
    printf("OOB boyutu (byte, orn: 128): ");
    scanf("%d", &chip.oob_size);
    printf("Blok boyutu (KB, orn: 128): ");
    int block_size_kb;
    scanf("%d", &block_size_kb);
    printf("Toplam blok sayisi: ");
    scanf("%d", &chip.total_blocks);
    while (getchar() != '\n');
    strncpy(chip.model, model, 63);
    chip.pages_per_block = (block_size_kb * 1024) / chip.data_size;

    cJSON *db = load_db();
    cJSON *nand = cJSON_GetObjectItem(db, "nand");
    if (!nand) {
        nand = cJSON_CreateObject();
        cJSON_AddItemToObject(db, "nand", nand);
    }
    cJSON *entry = cJSON_CreateObject();
    cJSON_AddStringToObject(entry, "model", chip.model);
    cJSON_AddNumberToObject(entry, "page_size", chip.data_size);   // veri boyutu
    cJSON_AddNumberToObject(entry, "oob_size", chip.oob_size);
    cJSON_AddNumberToObject(entry, "block_size_kb", block_size_kb);
    cJSON_AddNumberToObject(entry, "total_blocks", chip.total_blocks);
    cJSON_AddItemToObject(nand, chip_id_str, entry);
    save_db(db);
    cJSON_Delete(db);
    printf("[+] Veritabani guncellendi. Program yeniden baslatiliyor...\n");
}

/* ================================================================ *
 *  Bad block yönetimi                                               *
 * ================================================================ */
int is_bad_block(int block) {
    int page = block * chip.pages_per_block;
    int total = page_total();
    uint8_t *buf = malloc(total);
    if (!buf) return 1;
    if (nand_read_page(page, buf, 1) != 0) { free(buf); return 1; }
    // Fabrika bad block işareti: OOB ilk byte == 0x00
    int bad = (buf[chip.data_size] == 0x00);
    free(buf);
    return bad;
}

void scan_bad_blocks(int *bad_list, int *bad_count) {
    printf("[*] Bad block taramasi baslatildi (%d blok)...\n", chip.total_blocks);
    int count = 0;
    for (int b = 0; b < chip.total_blocks; b++) {
        if (is_bad_block(b)) bad_list[count++] = b;
        if ((b+1) % 50 == 0 || b == chip.total_blocks-1) {
            float perc = (b+1) * 100.0f / chip.total_blocks;
            int bar = (int)(perc / 4);
            printf("\rTARAMA |");
            for (int j = 0; j < 25; j++) printf("%c", j < bar ? '#' : ' ');
            printf("| %%%5.1f | %d/%d blok", perc, b+1, chip.total_blocks);
            fflush(stdout);
        }
    }
    *bad_count = count;
    printf("\n[+] Tarama tamamlandi. %d bozuk blok bulundu.\n", count);
    FILE *f = fopen("badblocks.txt", "w");
    if (f) {
        for (int i = 0; i < count; i++) fprintf(f, "%d\n", bad_list[i]);
        fclose(f);
    }
}

/* ================================================================ *
 *  Başlık ve ilerleme çubuğu                                        *
 * ================================================================ */
void print_header(const uint8_t *id, int bad_count) {
    int total_mb = chip.total_blocks * (page_total() * chip.pages_per_block) / (1024*1024);
    printf("\n============================================================\n");
    printf("  MODEL       : %s\n", chip.model);
    printf("  ID          : 0x%02X%02X%02X%02X%02X\n", id[0], id[1], id[2], id[3], id[4]);
    printf("  BOYUT       : %d MB\n", total_mb);
    printf("  SAYFA       : %d B + %d B OOB\n", chip.data_size, chip.oob_size);
    printf("  BLOK        : %d KB (%d sayfa/blok)\n", (page_total() * chip.pages_per_block)/1024, chip.pages_per_block);
    printf("  BLOK SAYISI : %d\n", chip.total_blocks);
    printf("  GECIKME     : %d us\n", delay_us);
    printf("  BAD BLOCK   : %d/%d\n", bad_count, chip.total_blocks);
    printf("============================================================\n");
}

void progress(const char *label, int current, int total, time_t start) {
    float perc = (current * 100.0f) / total;
    int bar = (int)(perc / 4);
    time_t now = time(NULL);
    int elapsed = (int)(now - start);
    char speed_str[64] = "";
    if (elapsed > 0) {
        float rate = current / (float)elapsed;
        snprintf(speed_str, sizeof(speed_str), "%.1f sayfa/s", rate);
    }
    printf("\r%s |", label);
    for (int j = 0; j < 25; j++) printf("%c", j < bar ? '#' : ' ');
    printf("| %%%5.1f | %s | %d/%d", perc, speed_str, current, total);
    fflush(stdout);
}

/* ================================================================ *
 *  Üst seviye işlemler                                              *
 * ================================================================ */
void do_read(int start_page, int end_page, const char *filename, int include_oob, const int *bad_list, int bad_count) {
    int total = end_page - start_page + 1;
    printf("[*] Okuma: sayfa %d-%d (%d sayfa), OOB=%s\n", start_page, end_page, total, include_oob ? "Evet" : "Hayir");
    FILE *f = fopen(filename, "wb");
    if (!f) { perror("fopen"); return; }
    int data_len = include_oob ? page_total() : chip.data_size;
    uint8_t *buf = malloc(page_total());  // her zaman tam sayfa okuyup yazacağız
    if (!buf) { fclose(f); return; }
    time_t start = time(NULL);
    int written = 0;
    for (int p = start_page; p <= end_page; p++) {
        int block = p / chip.pages_per_block;
        int skip = 0;
        for (int i = 0; i < bad_count; i++)
            if (bad_list[i] == block) { skip = 1; break; }
        if (skip) {
            memset(buf, 0xFF, data_len);
            fwrite(buf, data_len, 1, f);
            written++;
            continue;
        }
        if (nand_read_page(p, buf, include_oob) == 0) {
            fwrite(buf, data_len, 1, f);
            written++;
        }
        if (p % 10 == 0) progress("OKUMA", written, total, start);
    }
    fclose(f);
    free(buf);
    progress("OKUMA", total, total, start);
    printf("\n[+] Okuma tamamlandi.\n");
}

void do_write(int start_page, const char *filename, int include_oob, int erase_first, const int *bad_list, int bad_count) {
    int page_len = include_oob ? page_total() : chip.data_size;
    FILE *f = fopen(filename, "rb");
    if (!f) { perror("fopen"); return; }
    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    rewind(f);
    int total_pages = (fsize + page_len - 1) / page_len;
    printf("[*] Yazma: baslangic sayfa %d, dosya %s, OOB=%s\n", start_page, filename, include_oob ? "Evet" : "Hayir");

    if (erase_first) {
        int start_block = start_page / chip.pages_per_block;
        int end_block = (start_page + total_pages - 1) / chip.pages_per_block;
        printf("[*] Once bloklar siliniyor: %d-%d\n", start_block, end_block);
        for (int b = start_block; b <= end_block; b++) {
            int skip = 0;
            for (int i = 0; i < bad_count; i++) if (bad_list[i] == b) { skip = 1; break; }
            if (skip) continue;
            nand_erase_block(b);
        }
    }

    uint8_t *buf = malloc(page_total());
    if (!buf) { fclose(f); return; }
    time_t start = time(NULL);
    int written = 0, page = start_page;
    int *bad_set = calloc(chip.total_blocks, sizeof(int));
    for (int i = 0; i < bad_count; i++) bad_set[bad_list[i]] = 1;

    while (!feof(f)) {
        int block = page / chip.pages_per_block;
        if (bad_set[block]) {
            fseek(f, page_len * chip.pages_per_block, SEEK_CUR);
            page += chip.pages_per_block;
            continue;
        }
        size_t n = fread(buf, 1, page_len, f);
        if (n == 0) break;
        if (n < page_len) memset(buf + n, 0xFF, page_len - n);
        if (nand_write_page(page, buf, include_oob) == 0) written++;
        else bad_set[block] = 1;
        page++;
        if (written % 10 == 0) progress("YAZMA", written, total_pages, start);
    }
    fclose(f);
    free(buf);
    free(bad_set);
    progress("YAZMA", total_pages, total_pages, start);
    printf("\n[+] Yazma tamamlandi.\n");
}

void do_erase(int start_block, int end_block, const int *bad_list, int bad_count) {
    int total = end_block - start_block + 1;
    printf("[*] Silme: blok %d-%d (%d blok)\n", start_block, end_block, total);
    time_t start = time(NULL);
    int erased = 0;
    for (int b = start_block; b <= end_block; b++) {
        int skip = 0;
        for (int i = 0; i < bad_count; i++) if (bad_list[i] == b) { skip = 1; break; }
        if (skip) continue;
        if (nand_erase_block(b) == 0) erased++;
        if (erased % 5 == 0) progress("SILME", erased, total, start);
    }
    progress("SILME", total, total, start);
    printf("\n[+] Silme tamamlandi.\n");
}

/* ================================================================ *
 *  Ana menü                                                         *
 * ================================================================ */
int main() {
    int mem_fd;
    if ((mem_fd = open("/dev/gpiomem", O_RDWR | O_SYNC)) < 0) {
        perror("open /dev/gpiomem");
        return 1;
    }
    gpio = (volatile uint32_t*) mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, mem_fd, 0);
    if (gpio == MAP_FAILED) {
        perror("mmap");
        close(mem_fd);
        return 1;
    }

    OUT_GPIO(PIN_WP);  SET_GPIO(PIN_WP);
    OUT_GPIO(PIN_RE);  SET_GPIO(PIN_RE);
    OUT_GPIO(PIN_WE);  SET_GPIO(PIN_WE);
    OUT_GPIO(PIN_CLE); CLR_GPIO(PIN_CLE);
    OUT_GPIO(PIN_ALE); CLR_GPIO(PIN_ALE);
    INP_GPIO(PIN_RB);
    gpio_pull_up(PIN_RB);

    uint8_t id[5];
    nand_read_id(id);
    char id_str[16];
    snprintf(id_str, sizeof(id_str), "0x%02X%02X%02X%02X%02X", id[0], id[1], id[2], id[3], id[4]);
    printf("[*] Okunan ID: %s\n", id_str);

    if (!load_chip_from_db(id_str)) {
        add_chip_to_db(id_str);
        munmap((void*)gpio, 4096);
        close(mem_fd);
        execv("/proc/self/exe", NULL);
        return 0;
    }

    int total_pages = chip.total_blocks * chip.pages_per_block;
    int *bad_list = malloc(chip.total_blocks * sizeof(int));
    int bad_count = 0;
    scan_bad_blocks(bad_list, &bad_count);
    print_header(id, bad_count);

    while (1) {
        printf("\n--- ANA MENU ---\n");
        printf("1. OKU (OOB'siz)\n");
        printf("2. OKU (OOB'lu)\n");
        printf("3. YAZ (OOB'siz)\n");
        printf("4. YAZ (OOB'lu)\n");
        printf("5. SIL (blok araligi)\n");
        printf("6. BAD BLOCK TARAMA YENILE\n");
        printf("7. GECIKME AYARI (su an: %d us)\n", delay_us);
        printf("0. CIKIS\n");
        printf("Seciminiz: ");
        int choice;
        scanf("%d", &choice);
        while (getchar() != '\n');
        if (choice == 0) break;

        if (choice == 1 || choice == 2) {
            int include_oob = (choice == 2);
            char filename[256];
            int sp, ep;
            printf("Cikti dosya adi: ");
            fgets(filename, sizeof(filename), stdin);
            filename[strcspn(filename, "\n")] = 0;
            printf("Baslangic sayfasi (0-%d): ", total_pages-1); scanf("%d", &sp);
            printf("Bitis sayfasi: "); scanf("%d", &ep);
            while (getchar() != '\n');
            if (sp < 0) sp = 0;
            if (ep >= total_pages) ep = total_pages - 1;
            if (sp > ep) { int t = sp; sp = ep; ep = t; }
            do_read(sp, ep, filename, include_oob, bad_list, bad_count);
        }
        else if (choice == 3 || choice == 4) {
            int include_oob = (choice == 4);
            char filename[256];
            int sp;
            printf("Kaynak dosya adi: ");
            fgets(filename, sizeof(filename), stdin);
            filename[strcspn(filename, "\n")] = 0;
            printf("Baslangic sayfasi (0-%d): ", total_pages-1); scanf("%d", &sp);
            while (getchar() != '\n');
            printf("Once bloklar silinsin mi? (1=Evet, 0=Hayir): ");
            int erase_first;
            scanf("%d", &erase_first);
            while (getchar() != '\n');
            do_write(sp, filename, include_oob, erase_first, bad_list, bad_count);
            bad_count = 0;
            for (int b = 0; b < chip.total_blocks; b++) if (is_bad_block(b)) bad_list[bad_count++] = b;
        }
        else if (choice == 5) {
            int sb, eb;
            printf("Baslangic blogu (0-%d): ", chip.total_blocks-1); scanf("%d", &sb);
            printf("Bitis blogu: "); scanf("%d", &eb);
            while (getchar() != '\n');
            if (sb < 0) sb = 0;
            if (eb >= chip.total_blocks) eb = chip.total_blocks - 1;
            if (sb > eb) { int t = sb; sb = eb; eb = t; }
            do_erase(sb, eb, bad_list, bad_count);
            bad_count = 0;
            for (int b = 0; b < chip.total_blocks; b++) if (is_bad_block(b)) bad_list[bad_count++] = b;
        }
        else if (choice == 6) {
            bad_count = 0;
            scan_bad_blocks(bad_list, &bad_count);
            print_header(id, bad_count);
        }
        else if (choice == 7) {
            printf("Yeni gecikme (mikrosaniye, su an %d): ", delay_us);
            scanf("%d", &delay_us);
            while (getchar() != '\n');
            printf("Gecikme %d us olarak ayarlandi.\n", delay_us);
        }
        else {
            printf("Gecersiz secim!\n");
        }
    }

    free(bad_list);
    munmap((void*)gpio, 4096);
    close(mem_fd);
    printf("Program sonlandi.\n");
    return 0;
}
