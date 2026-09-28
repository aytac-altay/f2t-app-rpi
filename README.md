# F2T - Raspberry Pi Flash Memory Programmer & Analyzer Tool

[🇹🇷 Türkçe](#türkçe) | [🇬🇧 English](#english)

---

<a name="english"></a>
## 🇬🇧 English

An open-source flash programming and analysis toolkit running directly on Raspberry Pi to read (dump), write (flash), erase, and inspect hardware parameters of **SPI NAND**, **SPI NOR**, and **Parallel NAND (TSOP48)** flash memory chips.

### 🚀 Key Features

#### 1. SPI NAND Programming (`f2t_nand_spi.py`)
- Direct communication via Raspberry Pi hardware SPI interface (`spidev`).
- **Automatic Frequency Sweep:** Dynamically sweeps frequencies to measure the chip's maximum stable clock rate and recommends a safe operating speed (with 20% margin).
- **JSON-Based Chip Database (`nand_spi.json`):** Automatic chip identification via JEDEC ID, page/block size mapping, and dynamic saving of newly discovered chips.
- **Bad Block Scanning:** Scans and reports factory and runtime bad blocks (Bad Block Markers in OOB).
- **Write-Protection Unlock:** Automatically clears Status Register BP/SRP write-protection bits.
- Page-range raw dump, block-range erase, and file-to-page flashing.

#### 2. SPI NOR Programming (`f2t_nor_spi.py`)
- Full read, write, and erase support for standard SPI NOR flash chips (`nor_spi.json`).
- 4 KB sector erase, block erase, full-chip erase, and post-write verification.
- Safe chunking of large transfers according to Linux kernel SPI buffer limits.

#### 3. High-Speed Parallel NAND Programming (`build/f2t_nand_raw.c`)
- Direct BCM register I/O via `/dev/mem` (`mmap`), bypassing Linux GPIO driver overhead for maximum bit-banging throughput.
- Drives TSOP48 parallel NAND chips using an 8-bit parallel bus (GPIO 8–15) and control lines.
- Page read, write, and block erase with full OOB / Spare area support.

#### 4. Universal Hardware Scanner (`info_spi.py`)
- Standalone auto-detection of SPI NOR vs SPI NAND without database dependency.
- Queries **SFDP (0x5A)** and **ONFI (0xEC)** standard parameter tables.
- Measures maximum stable SPI frequency and calculates mathematical chip capacity.

---

### 🔌 Hardware Pinout

#### SPI NOR & SPI NAND (SPI0)
| Signal | Raspberry Pi Pin | Description |
| :--- | :--- | :--- |
| **MOSI** | GPIO 10 (Pin 19) | Master Out Slave In |
| **MISO** | GPIO 9 (Pin 21) | Master In Slave Out |
| **SCLK** | GPIO 11 (Pin 23) | SPI Clock |
| **CS0** | GPIO 8 (Pin 24) | Chip Select (CE#) |
| **VCC** | 3.3V (Pin 1 / 17) | 3.3V Power Supply |
| **GND** | GND (Pin 6 / 9 / 14 / ...) | Common Ground |

#### Parallel NAND (f2t_nand_raw)
| Signal | Raspberry Pi GPIO | Description |
| :--- | :--- | :--- |
| **WP#** | GPIO 2 | Write Protect |
| **R/B#** | GPIO 3 | Ready / Busy (internal pull-up) |
| **ALE** | GPIO 4 | Address Latch Enable |
| **CLE** | GPIO 5 | Command Latch Enable |
| **RE#** | GPIO 6 | Read Enable |
| **WE#** | GPIO 7 | Write Enable |
| **I/O 0 - 7**| GPIO 8 - GPIO 15 | 8-bit Data Bus |
| **CE#** | GND | Chip Enable (Permanently Active) |

---

### 🛠️ Installation & Usage

#### Prerequisites (on Raspberry Pi):
```bash
sudo apt update
sudo apt install -y python3-spidev python3-rpi.gpio build-essential
```

#### 1. SPI NAND Operations
```bash
python3 f2t_nand_spi.py
```

#### 2. SPI NOR Operations
```bash
python3 f2t_nor_spi.py
```

#### 3. Compile and Run Parallel NAND Programmer
```bash
cd build
gcc -O2 -Wall -o ../f2t_nand_raw f2t_nand_raw.c cJSON.c -lm
cd ..
sudo ./f2t_nand_raw
```

#### 4. Chip Detection & Diagnostics
```bash
python3 info_spi.py
```

---

### 📁 Project Structure

```
├── f2t_nand_spi.py      # SPI NAND programming tool
├── f2t_nor_spi.py       # SPI NOR programming tool
├── info_spi.py          # Fast hardware, SFDP, and ONFI scanner
├── nand_spi.json        # SPI NAND chip parameters database
├── nor_spi.json         # SPI NOR chip parameters database
├── nand_paralel.json    # Parallel NAND chip parameters database
├── build/               # C-based parallel NAND driver source code
│   ├── f2t_nand_raw.c
│   ├── cJSON.c
│   └── cJSON.h
├── .gitignore           # Ignores test dumps and incomplete files
└── README.md
```

---

<a name="türkçe"></a>
## 🇹🇷 Türkçe

Raspberry Pi donanımı üzerinde çalışan; **SPI NAND**, **SPI NOR** ve **Paralel NAND (TSOP48)** flash bellekleri okumak (dump), yazmak (flash), silmek (erase) ve donanımsal parametrelerini analiz etmek için geliştirilmiş açık kaynaklı flash programlama araç setidir.

### 🚀 Temel Özellikler

#### 1. SPI NAND Programlama (`f2t_nand_spi.py`)
- Raspberry Pi donanımsal SPI arayüzü (`spidev`) üzerinden doğrudan iletişim.
- **Otomatik Frekans Taraması:** Çipin kararlı çalışabileceği en yüksek frekansı test ederek güvenli çalışma hızını (%80 pay) otomatik belirleme.
- **JSON Tabanlı Çip Veritabanı (`nand_spi.json`):** JEDEC ID üzerinden çip tanıma, sayfa/blok boyutlarını otomatik eşleme ve yeni çipleri kaydedebilme.
- **Bad Block Taraması:** Flash bellek üzerindeki bozuk blokları (Bad Block Marker) tarama ve listeleme.
- **Yazma Koruması (Write Protection) Kaldırma:** Status Register üzerindeki BP/SRP korumalarını otomatik devre dışı bırakma.
- Sayfa aralığına göre ham okuma (dump), blok aralığına göre silme ve dosyadan sayfa bazlı yazma.

#### 2. SPI NOR Programlama (`f2t_nor_spi.py`)
- Standart SPI NOR flash yongaları (`nor_spi.json`) için okuma, yazma ve silme desteği.
- 4 KB sektör silme, blok silme, tam çip silme ve yazılan veriyi doğrulama (verification).
- Büyük veri transferlerini kernel buffer limitine uygun olarak güvenli parçalara ayırma.

#### 3. Yüksek Hızlı Paralel NAND Programlama (`build/f2t_nand_raw.c`)
- Standart Linux GPIO sürücü gecikmelerini atlayarak `/dev/mem` üzerinden doğrudan BCM donanım register'larına erişim (`mmap`).
- 8-bit paralel veri yolu (GPIO 8-15) ve kontrol hatları ile TSOP48 paralel NAND yongalarını sürme.
- OOB/Spare verisiyle birlikte sayfa okuma, yazma ve blok silme.

#### 4. Evrensel Donanım Tarayıcı (`info_spi.py`)
- Veritabanına ihtiyaç duymadan SPI NOR ve SPI NAND bellekleri otomatik ayırt etme.
- **SFDP (0x5A)** ve **ONFI (0xEC)** standart parametre sayfalarını sorgulama.
- Çipin maksimum stabil SPI hızını ve teorik kapasitesini belirleme.

---

### 🔌 Donanım Bağlantıları (Pinout)

#### SPI NOR & SPI NAND (Standart SPI0)
| Sinyal | Raspberry Pi Pin | Açıklama |
| :--- | :--- | :--- |
| **MOSI** | GPIO 10 (Pin 19) | Master Out Slave In |
| **MISO** | GPIO 9 (Pin 21) | Master In Slave Out |
| **SCLK** | GPIO 11 (Pin 23) | SPI Clock |
| **CS0** | GPIO 8 (Pin 24) | Chip Select (CE#) |
| **VCC** | 3.3V (Pin 1 / 17) | 3.3V Besleme |
| **GND** | GND (Pin 6 / 9 / 14 / ...) | Ortak Toprak |

#### Paralel NAND (f2t_nand_raw)
| Sinyal | Raspberry Pi GPIO | Açıklama |
| :--- | :--- | :--- |
| **WP#** | GPIO 2 | Write Protect |
| **R/B#** | GPIO 3 | Ready / Busy (dahili pull-up) |
| **ALE** | GPIO 4 | Address Latch Enable |
| **CLE** | GPIO 5 | Command Latch Enable |
| **RE#** | GPIO 6 | Read Enable |
| **WE#** | GPIO 7 | Write Enable |
| **I/O 0 - 7**| GPIO 8 - GPIO 15 | 8-bit Veri Yolu |
| **CE#** | GND | Chip Enable (Sürekli aktif) |

---

### 🛠️ Kurulum ve Kullanım

#### Gereksinimler (Raspberry Pi üzerinde):
```bash
sudo apt update
sudo apt install -y python3-spidev python3-rpi.gpio build-essential
```

#### 1. SPI NAND Bellek İşlemleri
```bash
python3 f2t_nand_spi.py
```

#### 2. SPI NOR Bellek İşlemleri
```bash
python3 f2t_nor_spi.py
```

#### 3. Paralel NAND Programlayıcıyı Derleme ve Çalıştırma
```bash
cd build
gcc -O2 -Wall -o ../f2t_nand_raw f2t_nand_raw.c cJSON.c -lm
cd ..
sudo ./f2t_nand_raw
```

#### 4. Çip Tespiti ve Parametre Taraması
```bash
python3 info_spi.py
```

---

### 📁 Proje Dosya Yapısı

```
├── f2t_nand_spi.py      # SPI NAND programlama aracı
├── f2t_nor_spi.py       # SPI NOR programlama aracı
├── info_spi.py          # Hızlı donanım, SFDP ve ONFI tarayıcı
├── nand_spi.json        # SPI NAND çip veritabanı
├── nor_spi.json         # SPI NOR çip veritabanı
├── nand_paralel.json    # Paralel NAND çip veritabanı
├── build/               # C tabanlı paralel NAND sürücü kaynak kodları
│   ├── f2t_nand_raw.c
│   ├── cJSON.c
│   └── cJSON.h
├── .gitignore           # Test dökümleri ve tamamlanmamış dosyaları hariç tutar
└── README.md
```