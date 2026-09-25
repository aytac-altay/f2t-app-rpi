# F2T - Raspberry Pi Flash Bellek Programlama ve Analiz Aracı

Raspberry Pi donanımı üzerinde çalışan; **SPI NAND**, **SPI NOR** ve **Paralel NAND (TSOP48)** flash bellekleri okumak (dump), yazmak (flash), silmek (erase) ve donanımsal parametrelerini analiz etmek için geliştirilmiş açık kaynaklı flash programlama araç setidir.

---

## 🚀 Temel Özellikler

### 1. SPI NAND Programlama (`f2t_nand_spi.py`)
- Raspberry Pi donanımsal SPI arayüzü (`spidev`) üzerinden doğrudan iletişim.
- **Otomatik Frekans Taraması:** Çipin kararlı çalışabileceği en yüksek frekansı test ederek güvenli çalışma hızını (%80 pay) otomatik belirleme.
- **JSON Tabanlı Çip Veritabanı (`nand_spi.json`):** JEDEC ID üzerinden çip tanıma, sayfa/blok boyutlarını otomatik eşleme ve yeni çipleri kaydedebilme.
- **Bad Block Taraması:** Flash bellek üzerindeki bozuk blokları (Bad Block Marker) tarama ve listeleme.
- **Yazma Koruması (Write Protection) Kaldırma:** Status Register üzerindeki BP/SRP korumalarını otomatik devre dışı bırakma.
- Sayfa aralığına göre ham okuma (dump), blok aralığına göre silme ve dosyadan sayfa bazlı yazma.

### 2. SPI NOR Programlama (`f2t_nor_spi.py`)
- Standart SPI NOR flash yongaları (`nor_spi.json`) için okuma, yazma ve silme desteği.
- 4 KB sektör silme, blok silme, tam çip silme ve yazılan veriyi doğrulama (verification).
- Büyük veri transferlerini kernel buffer limitine uygun olarak güvenli parçalara ayırma.

### 3. Yüksek Hızlı Paralel NAND Programlama (`build/f2t_nand_raw.c`)
- Standart Linux GPIO sürücü gecikmelerini atlayarak `/dev/mem` üzerinden doğrudan BCM donanım register'larına erişim (`mmap`).
- 8-bit paralel veri yolu (GPIO 8-15) ve kontrol hatları ile TSOP48 paralel NAND yongalarını sürme.
- OOB/Spare verisiyle birlikte sayfa okuma, yazma ve blok silme.

### 4. Evrensel Donanım Tarayıcı (`info_spi.py`)
- Veritabanına ihtiyaç duymadan SPI NOR ve SPI NAND bellekleri otomatik ayırt etme.
- **SFDP (0x5A)** ve **ONFI (0xEC)** standart parametre sayfalarını sorgulama.
- Çipin maksimum stabil SPI hızını ve teorik kapasitesini belirleme.

---

## 🔌 Donanım Bağlantıları (Pinout)

### SPI NOR & SPI NAND (Standart SPI0)
| Sinyal | Raspberry Pi Pin | Açıklama |
| :--- | :--- | :--- |
| **MOSI** | GPIO 10 (Pin 19) | Master Out Slave In |
| **MISO** | GPIO 9 (Pin 21) | Master In Slave Out |
| **SCLK** | GPIO 11 (Pin 23) | SPI Clock |
| **CS0** | GPIO 8 (Pin 24) | Chip Select (CE#) |
| **VCC** | 3.3V (Pin 1 / 17) | 3.3V Besleme |
| **GND** | GND (Pin 6 / 9 / 14 / ...) | Ortak Toprak |

### Paralel NAND (f2t_nand_raw)
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

## 🛠️ Kurulum ve Kullanım

### Gereksinimler (Raspberry Pi üzerinde):
```bash
sudo apt update
sudo apt install -y python3-spidev python3-rpi.gpio build-essential
```

### 1. SPI NAND Bellek İşlemleri
```bash
python3 f2t_nand_spi.py
```

### 2. SPI NOR Bellek İşlemleri
```bash
python3 f2t_nor_spi.py
```

### 3. Paralel NAND Programlayıcıyı Derleme ve Çalıştırma
```bash
cd build
gcc -O2 -Wall -o ../f2t_nand_raw f2t_nand_raw.c cJSON.c -lm
cd ..
sudo ./f2t_nand_raw
```

### 4. Çip Tespiti ve Parametre Taraması
```bash
python3 info_spi.py
```

---

## 📁 Proje Dosya Yapısı

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
