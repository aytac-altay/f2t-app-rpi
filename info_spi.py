#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import spidev
import time

def get_id(speed, mode=0):
    """Belirli bir hızda ID okur."""
    spi = spidev.SpiDev()
    try:
        spi.open(0, 0)
        spi.max_speed_hz = speed
        spi.mode = mode
        # 0x9F komutu hem NOR hem NAND (dummy ile) için yeterli 6 byte
        raw = spi.xfer2([0x9F, 0x00, 0x00, 0x00, 0x00, 0x00])
        return raw[1:]
    except:
        return None
    finally:
        spi.close()

def sweep_frequency():
    """Frekansı artırarak çipin yanıt verme limitini ölçer."""
    test_speeds = [1000000, 10000000, 20000000, 40000000, 60000000, 80000000, 100000000]
    base_id = get_id(1000000)
    
    if all(x in [0x00, 0xFF] for x in base_id[:3]):
        return None, 0
    
    max_stable = 1000000
    for speed in test_speeds:
        current_id = get_id(speed)
        if current_id == base_id:
            max_stable = speed
        else:
            break
    return base_id, max_stable

def read_sfdp_raw():
    """SFDP (Serial Flash Discoverable Parameters) tablosunu sorgular."""
    spi = spidev.SpiDev()
    spi.open(0, 1)
    spi.max_speed_hz = 1000000
    # 0x5A (SFDP Read) + 3 Byte Adres + 1 Dummy + 8 Byte Veri
    res = spi.xfer2([0x5A, 0x00, 0x00, 0x00, 0x00] + [0x00]*8)
    spi.close()
    sig = "".join([chr(x) for x in res[5:9]])
    return sig if sig == "SFDP" else None

def get_nand_params():
    """SPI NAND ONFI parametre sayfasını okumayı dener."""
    spi = spidev.SpiDev()
    spi.open(0, 1)
    spi.max_speed_hz = 1000000
    # 0xEC (Read Parameter Page) + 1 Dummy + 4 Byte Veri
    res = spi.xfer2([0xEC, 0x00, 0x00, 0x00, 0x00, 0x00])
    spi.close()
    sig = "".join([chr(x) for x in res[2:6]])
    return sig if sig == "ONFI" else None

def run_info():
    print("="*50)
    print(f"{'EVRENSEL DONANIM TARAYICI (DB-SIZ)':^50}")
    print("="*50)

    # 1. Frekans ve ID Analizi
    raw_id, max_f = sweep_frequency()
    
    if not raw_id:
        print("HATA: Çip algılanamadı! Bağlantıları kontrol edin.")
        return

    # 2. Tür Belirleme
    if raw_id[0] not in [0x00, 0xFF]:
        chip_kind = "SPI NOR"
        man_id, m_type, cap_id = raw_id[0], raw_id[1], raw_id[2]
        # JEDEC Standardı: 2^n bayt
        cap_val = (2**cap_id) / (1024*1024) if cap_id < 0x20 else 0
        cap_info = f"{cap_val:.2f} MB"
    else:
        chip_kind = "SPI NAND"
        man_id, m_type, cap_id = raw_id[1], raw_id[2], raw_id[3]
        cap_info = "Belirlenemedi (NAND Datasheet gerekebilir)"

    # 3. Sonuçları Yazdır
    print(f"Tespit Edilen Tür      : {chip_kind}")
    print(f"Üretici ID             : 0x{man_id:02X}")
    print(f"Cihaz/Kapasite Kodu    : 0x{m_type:02X} / 0x{cap_id:02X}")
    print(f"Ham ID Verisi          : {[hex(x) for x in raw_id[:5]]}")
    print(f"Matematiksel Kapasite  : {cap_info}")
    
    print("-" * 50)
    
    # 4. Frekans Analizi Sonucu
    print(f"Maksimum Kararlı Hız   : {max_f / 1000000:.1f} MHz")
    print(f"Önerilen Çalışma Hızı  : {max_f * 0.8 / 1000000:.1f} MHz (Güvenli %80)")

    print("-" * 50)

    # 5. Standart Uyumluluk
    if chip_kind == "SPI NOR":
        if read_sfdp_raw():
            print("SFDP (JEDEC) Desteği   : VAR (Standart Veri Okunabilir)")
        else:
            print("SFDP (JEDEC) Desteği   : YOK (Eski Nesil NOR)")
    else:
        if get_nand_params():
            print("ONFI (NAND) Desteği    : VAR (Parametre Sayfası Mevcut)")
        else:
            print("ONFI (NAND) Desteği    : YOK (Özel Komut Seti Gerekebilir)")

    print("="*50)

if __name__ == "__main__":
    run_info()


