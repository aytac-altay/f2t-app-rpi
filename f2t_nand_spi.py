#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# spinand-tool.py  —  Raspberry Pi için SPI NAND programlama aracı
#
# Özellikler:
#   - Otomatik optimum SPI hızı algılama ve seçme
#   - JSON veritabanından çip tanıma, yoksa kullanıcıdan bilgi alıp kaydetme
#   - ONFI desteği kontrolü
#   - Bad block taraması ve header’da gösterimi
#   - NAND kendi OOB/ECC’sini yönetir; program sadece ham veri okur/yazar
#   - Basit ve gelişmiş menü

import spidev
import os
import sys
import time
import json

# SPI buffer ayarları (kernel spidev.bufsiz ile artırılabilir)
_SPI_MAX_XFER = 4096          # varsayılan kernel değeri
_SPI_SAFE_DATA = _SPI_MAX_XFER - 8


class SPINandTool:
    def __init__(self):
        self.spi = spidev.SpiDev()
        self.db_path = 'nand_spi.json'
        self.chip_db = self.load_db()
        self.chip_info = None
        self.chip_id = None
        self.speed = 8_000_000       # başlangıç, sonra kullanıcı seçecek
        self.bad_blocks = []
        self.onfi_support = False
        self.protected = False

    # ------------------------------------------------------------------ #
    #  Veritabanı işlemleri                                               #
    # ------------------------------------------------------------------ #

    def load_db(self):
        """
        Veritabanını yükler. Dosya yoksa veya bozuksa, boş bir yapıyla
        yoluna devam eder. Bu sayede çip tanınamazsa kullanıcıya sorulur.
        """
        if not os.path.exists(self.db_path):
            # Dosya hiç yok → boş bir veritabanı oluştur
            default_db = {"nand": {}}
            with open(self.db_path, 'w') as f:
                json.dump(default_db, f, indent=2)
            print("[*] Yeni boş veritabanı oluşturuldu.")
            return default_db

        # Dosya var, geçerli JSON olup olmadığını dene
        try:
            with open(self.db_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Veritabanı okunamadı ({e}). Bozuk dosya yedekleniyor...")
            # Bozuk dosyayı yedekle
            backup_name = self.db_path + ".bak"
            try:
                os.rename(self.db_path, backup_name)
                print(f"    Eski dosya '{backup_name}' olarak saklandı.")
            except Exception:
                pass
            # Yeni boş veritabanı oluştur
            default_db = {"nand": {}}
            with open(self.db_path, 'w') as f:
                json.dump(default_db, f, indent=2)
            print("[+] Yeni boş veritabanı oluşturuldu.")
            return default_db

    def save_db(self):
        try:
            with open(self.db_path, 'w') as f:
                json.dump(self.chip_db, f, indent=2)
        except Exception as e:
            print(f"Veritabanı yazılamadı: {e}")

    # ------------------------------------------------------------------ #
    #  SPI yardımcıları                                                   #
    # ------------------------------------------------------------------ #

    def open_spi(self, speed=None):
        if speed is None:
            speed = self.speed
        try:
            self.spi.open(0, 0)
            self.spi.max_speed_hz = int(speed)
            self.spi.mode = 0
            self.spi.no_cs = False
            self.spi.lsbfirst = False
            self.spi.bits_per_word = 8
        except Exception as e:
            print(f"SPI açılamadı: {e}")
            sys.exit(1)

    def close_spi(self):
        self.spi.close()

    def _xfer(self, data):
        """Büyük verileri otomatik parçalayarak transfer eder."""
        if len(data) <= _SPI_MAX_XFER:
            return self.spi.xfer2(data)
        result = []
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + _SPI_MAX_XFER]
            result.extend(self.spi.xfer2(chunk))
            offset += _SPI_MAX_XFER
        return result

    # ------------------------------------------------------------------ #
    #  Hız algılama ve seçimi                                             #
    # ------------------------------------------------------------------ #

    def detect_optimal_speeds(self):
        """Bir dizi frekansı dener, JEDEC ID okuyarak çalışanları listeler."""
        test_speeds = [500_000, 1_000_000, 2_000_000, 4_000_000,
                       8_000_000, 16_000_000, 32_000_000]
        working = []
        print("[*] Çalışma frekansları taranıyor...")
        for speed in test_speeds:
            try:
                self.open_spi(speed)
                # JEDEC ID oku (0x9F)
                resp = self.spi.xfer2([0x9F, 0x00, 0x00, 0x00])
                # En azından 2. byte anlamlı bir şey içeriyor mu?
                if resp[1] != 0xFF and resp[2] != 0xFF:
                    chip_id = "0x" + "".join(f"{x:02X}" for x in resp[1:4])
                    working.append((speed, chip_id))
                    print(f"   {speed/1e6:.1f} MHz  : OK  (ID: {chip_id})")
                else:
                    print(f"   {speed/1e6:.1f} MHz  : cevap yok")
            except Exception as e:
                print(f"   {speed/1e6:.1f} MHz  : hata ({e})")
            finally:
                self.close_spi()
        if not working:
            print("[!] Hiçbir frekansta çip ile haberleşilemedi!")
            sys.exit(1)
        return working

    def select_speed(self):
        working = self.detect_optimal_speeds()
        print("\nSPI Hız Seçimi:")
        for idx, (speed, _) in enumerate(working):
            print(f"  {chr(ord('a')+idx)}) {speed/1e6:.1f} MHz")
        while True:
            choice = input("Seçiminiz (varsayılan en yüksek): ").strip().lower()
            if choice == "":
                # En yüksek frekansı al
                self.speed = working[-1][0]
                break
            idx = ord(choice) - ord('a')
            if 0 <= idx < len(working):
                self.speed = working[idx][0]
                break
            print("Geçersiz seçim!")
        print(f"[+] Hız {self.speed/1e6:.1f} MHz seçildi.")

    # ------------------------------------------------------------------ #
    #  Çip tanıma                                                         #
    # ------------------------------------------------------------------ #

    def detect_chip(self):
        """SPI ile çipi tanır, veritabanında varsa bilgileri yükler.
        Yoksa kullanıcıdan bilgi alıp veritabanına ekler ve programı yeniden başlatır."""
        self.open_spi(self.speed)
        raw = self.spi.xfer2([0x9F] + [0x00]*3)
        chip_id = "0x" + "".join(f"{x:02X}" for x in raw[1:4])
        # NAND veritabanında ara
        if "nand" in self.chip_db and chip_id in self.chip_db["nand"]:
            self.chip_info = self.chip_db["nand"][chip_id]
            self.chip_id = chip_id
            print(f"[+] Çip tanındı: {self.chip_info['model']} (ID: {chip_id})")
            return True
        else:
            print(f"[!] {chip_id} ID'li çip veritabanında bulunamadı.")
            print("Lütfen aşağıdaki bilgileri girin (sayısal değerler):")
            model = input("Model adı: ").strip()
            page_size = int(input("Sayfa boyutu (byte, örn: 2048): "))
            oob_size = int(input("OOB boyutu (byte, örn: 64): "))
            block_size_kb = int(input("Blok boyutu (KB, örn: 128): "))
            total_blocks = int(input("Toplam blok sayısı: "))
            self.chip_info = {
                "model": model,
                "page_size": page_size,
                "oob_size": oob_size,
                "block_size_kb": block_size_kb,
                "total_blocks": total_blocks
            }
            if "nand" not in self.chip_db:
                self.chip_db["nand"] = {}
            self.chip_db["nand"][chip_id] = self.chip_info
            self.save_db()
            print("[+] Veritabanı güncellendi. Program yeniden başlatılıyor...")
            self.close_spi()
            # Kendini yeniden başlat
            os.execv(sys.executable, [sys.executable] + sys.argv)

    def check_onfi(self):
        """ONFI desteğini test eder (Read Parameter Page komutu)."""
        try:
            resp = self.spi.xfer2([0xEC, 0x00, 0x00, 0x00, 0x00])
            if bytes(resp[1:5]) == b'ONFI':
                self.onfi_support = True
            else:
                self.onfi_support = False
        except Exception:
            self.onfi_support = False

    # ------------------------------------------------------------------ #
    #  NAND durum ve kontrol                                              #
    # ------------------------------------------------------------------ #

    def nand_read_status(self):
        """Status Register oku (NAND komut seti)."""
        resp = self.spi.xfer2([0x0F, 0xC0, 0x00])
        return resp[2]

    def nand_wait_busy(self, check_error=False):
        """Meşgul bayrağı kalkana kadar bekle."""
        time.sleep(0.001)
        while True:
            status = self.nand_read_status()
            if not (status & 0x01):  # BUSY biti 0?
                if check_error and (status & 0x04):  # HATA biti?
                    raise RuntimeError("Flash işlem hatası!")
                break
            time.sleep(0.001)
        time.sleep(0.0001)  # settle

    def nand_write_enable(self):
        """Write Enable gönder ve WE bitinin setlendiğini kontrol et."""
        self.spi.xfer2([0x06])
        time.sleep(0.001)
        if not (self.nand_read_status() & 0x02):
            raise RuntimeError("Write Enable başarısız!")

    def nand_check_write_protection(self):
        """BP bitlerini oku, koruma durumunu döndür."""
        resp = self.spi.xfer2([0x0F, 0xA0, 0x00])
        prot = resp[2]
        bp_bits = (prot >> 2) & 0x07
        srp_bits = (prot >> 6) & 0x03
        return bp_bits != 0, srp_bits != 0

    def nand_unlock_all(self):
        """Tüm BP bitlerini sıfırlayarak yazma korumasını kaldır."""
        try:
            self.nand_write_enable()
        except RuntimeError:
            print("[!] Write Enable yapılamadı, kilit kaldırılamadı.")
            return
        self.spi.xfer2([0x1F, 0xA0, 0x00])
        time.sleep(0.015)
        self.nand_wait_busy()
        protected, hw_lock = self.nand_check_write_protection()
        if protected:
            print("[!] Koruma hâlâ aktif.")
        else:
            print("[+] Tüm yazma koruması kaldırıldı.")

    # ------------------------------------------------------------------ #
    #  Sayfa okuma / yazma                                                #
    # ------------------------------------------------------------------ #

    def nand_read_page(self, page_addr, include_oob=False):
        """Bir sayfayı oku; include_oob=False ise sadece ana veriyi döndür."""
        ps = self.chip_info['page_size']
        oob = self.chip_info['oob_size']
        read_len = ps + (oob if include_oob else 0)

        # Sayfayı cache'e yükle (0x13)
        self.spi.xfer2([0x13,
                        (page_addr >> 16) & 0xFF,
                        (page_addr >> 8) & 0xFF,
                         page_addr & 0xFF])
        self.nand_wait_busy()
        time.sleep(0.0001)   # settle

        # Cache'den oku (0x0B), kolon 0
        header = [0x0B, 0x00, 0x00, 0x00]  # 1 dummy byte
        if read_len <= _SPI_SAFE_DATA:
            rx = self.spi.xfer2(header + [0x00] * read_len)
            return bytes(rx[4:])
        else:
            # Büyük veri parçalı okuma
            first_chunk = _SPI_SAFE_DATA
            rx = self.spi.xfer2(header + [0x00] * first_chunk)
            result = bytearray(rx[4:])
            remaining = read_len - first_chunk
            while remaining > 0:
                chunk = min(_SPI_SAFE_DATA, remaining)
                rx = self.spi.xfer2([0x00] * chunk)
                result.extend(rx)
                remaining -= chunk
            return bytes(result[:read_len])

    def nand_write_page(self, page_addr, data):
        """Bir sayfaya (sadece ana veri) yazar. NAND kendi ECC'sini ekler."""
        ps = self.chip_info['page_size']
        if len(data) != ps:
            raise ValueError(f"Veri boyutu {ps} olmalı, {len(data)} geldi.")

        self.nand_write_enable()

        # Program Load (0x02) - kolon 0'dan başla
        load_header = [0x02, 0x00, 0x00]
        if len(data) <= _SPI_SAFE_DATA:
            self.spi.xfer2(load_header + list(data))
        else:
            # Parçalı yükleme
            self.spi.xfer2(load_header + list(data[:_SPI_SAFE_DATA]))
            offset = _SPI_SAFE_DATA
            while offset < len(data):
                chunk = data[offset:offset+_SPI_SAFE_DATA]
                self.spi.xfer2(chunk)
                offset += _SPI_SAFE_DATA

        time.sleep(0.0001)  # settle

        # Program Execute (0x10)
        self.spi.xfer2([0x10,
                        (page_addr >> 16) & 0xFF,
                        (page_addr >> 8) & 0xFF,
                         page_addr & 0xFF])
        self.nand_wait_busy(check_error=True)

    # ------------------------------------------------------------------ #
    #  Blok silme                                                         #
    # ------------------------------------------------------------------ #

    def nand_erase_block(self, block_addr):
        """Tek bir bloğu sil (0xD8). Başarısız olursa bad block olarak işaretlenir."""
        ppb = (self.chip_info['block_size_kb'] * 1024) // self.chip_info['page_size']
        page_addr = block_addr * ppb
        self.nand_write_enable()
        self.spi.xfer2([0xD8,
                        (page_addr >> 16) & 0xFF,
                        (page_addr >> 8) & 0xFF,
                         page_addr & 0xFF])
        try:
            self.nand_wait_busy(check_error=True)
        except RuntimeError:
            # Hata durumunda bad block listesine ekle, status'u temizle
            self.bad_blocks.append(block_addr)
            self.spi.xfer2([0x1F, 0xC0, 0x00])  # Clear Status
            time.sleep(0.002)
            raise   # üst katmana bildir

    # ------------------------------------------------------------------ #
    #  Bad block yönetimi                                                 #
    # ------------------------------------------------------------------ #

    def nand_check_bad_block(self, block_addr):
        """Bloğun ilk sayfasının yedek alanının ilk baytına bakarak bad block kontrolü yapar."""
        ppb = (self.chip_info['block_size_kb'] * 1024) // self.chip_info['page_size']
        page = block_addr * ppb
        oob = self.chip_info['oob_size']
        ps = self.chip_info['page_size']
        # Sayfayı cache'e al, sonra OOB'un ilk baytını oku
        self.spi.xfer2([0x13,
                        (page >> 16) & 0xFF,
                        (page >> 8) & 0xFF,
                         page & 0xFF])
        self.nand_wait_busy()
        time.sleep(0.0001)
        col = ps  # OOB başlangıcı
        resp = self.spi.xfer2([0x0B,
                               (col >> 8) & 0xFF,
                                col & 0xFF,
                               0x00,      # dummy
                               0x00])     # 1 byte oku
        marker = resp[4]
        return marker != 0xFF

    def scan_bad_blocks(self):
        """Tüm blokları tara, bad block listesini güncelle."""
        total = self.chip_info['total_blocks']
        self.bad_blocks = []
        print(f"[*] Bad block taraması başlatıldı ({total} blok)...")
        start_time = time.time()
        for b in range(total):
            if self.nand_check_bad_block(b):
                self.bad_blocks.append(b)
            self._progress(b + 1, total, start_time, "TARAMA", "blok")
        print(f"\n[+] Tarama tamamlandı. {len(self.bad_blocks)} bozuk blok bulundu.")
        # Listeyi dosyaya kaydet (isteğe bağlı)
        with open(f"badblocks_{self.chip_info['model']}.txt", 'w') as f:
            f.write("\n".join(str(x) for x in sorted(self.bad_blocks)))

    # ------------------------------------------------------------------ #
    #  Üst seviye işlemler (menüden çağrılan)                             #
    # ------------------------------------------------------------------ #

    def read_pages(self, start_page, end_page, filename):
        """Belirtilen sayfa aralığını oku (OOB'siz) ve dosyaya yaz."""
        ps = self.chip_info['page_size']
        total_pages = self.chip_info['total_blocks'] * (self.chip_info['block_size_kb'] * 1024 // ps)
        if end_page >= total_pages:
            end_page = total_pages - 1
        total = end_page - start_page + 1
        print(f"[*] Okuma: {start_page}-{end_page} ({total} sayfa)")
        start_t = time.time()
        with open(filename, 'wb') as f:
            for p in range(start_page, end_page + 1):
                data = self.nand_read_page(p, include_oob=False)
                f.write(data)
                self._progress(p - start_page + 1, total, start_t, "OKUMA", "sayfa")
        print()

    def write_pages(self, start_page, filename, erase_first=False):
        """Dosyadan sayfa sayfa okur ve NAND'a yazar (sadece ana veri)."""
        ps = self.chip_info['page_size']
        ppb = (self.chip_info['block_size_kb'] * 1024) // ps
        if not os.path.exists(filename):
            print("Dosya bulunamadı.")
            return
        file_size = os.path.getsize(filename)
        total_pages_needed = (file_size + ps - 1) // ps
        total_pages_available = self.chip_info['total_blocks'] * ppb
        if start_page + total_pages_needed > total_pages_available:
            print("HATA: Dosya çip kapasitesini aşıyor.")
            return

        # İstenirse önce blokları sil
        if erase_first:
            end_page = start_page + total_pages_needed - 1
            start_block = start_page // ppb
            end_block = end_page // ppb
            self.erase_blocks(start_block, end_block)

        print(f"[*] Yazma: başlangıç sayfası {start_page}, dosya {filename}")
        start_t = time.time()
        bad_list = set(self.bad_blocks)
        written = 0
        with open(filename, 'rb') as f:
            page = start_page
            while True:
                # Bad block atla
                block = page // ppb
                if block in bad_list:
                    skip = ppb - (page % ppb)
                    f.seek(skip * ps, 1)  # dosyada ilerle
                    page += skip
                    continue
                chunk = f.read(ps)
                if not chunk:
                    break
                # Son sayfayı 0xFF ile doldur
                if len(chunk) < ps:
                    chunk = chunk.ljust(ps, b'\xff')
                try:
                    self.nand_write_page(page, chunk)
                except RuntimeError:
                    print(f"\n[!] Sayfa {page} yazılamadı (bad block olabilir).")
                    self.bad_blocks.append(block)
                    bad_list.add(block)
                page += 1
                written += 1
                self._progress(f.tell(), file_size, start_t, "YAZMA", "B")
        print()

    def erase_blocks(self, start_block, end_block):
        """Belirtilen blok aralığını sil."""
        total = self.chip_info['total_blocks']
        if end_block >= total:
            end_block = total - 1
        count = end_block - start_block + 1
        print(f"[*] Silme: blok {start_block}-{end_block} ({count} blok)")
        start_t = time.time()
        for b in range(start_block, end_block + 1):
            try:
                self.nand_erase_block(b)
            except RuntimeError:
                print(f"\n[!] Blok {b} silinemedi (bad block olarak işaretlendi).")
            self._progress(b - start_block + 1, count, start_t, "SİLME", "blok")
        print()

    # ------------------------------------------------------------------ #
    #  Header ve yardımcı fonksiyonlar                                    #
    # ------------------------------------------------------------------ #

    def print_header(self):
        info = self.chip_info
        total_mb = info['total_blocks'] * info['block_size_kb'] // 1024
        ppb = (info['block_size_kb'] * 1024) // info['page_size']
        total_pages = info['total_blocks'] * ppb
        protected, hw_lock = self.nand_check_write_protection()
        self.protected = protected
        prot_str = "EVET" if protected else "HAYIR"
        if hw_lock:
            prot_str += " (HW kilitli)"
        onfi_str = "EVET" if self.onfi_support else "HAYIR"
        bad_str = f"{len(self.bad_blocks)}/{info['total_blocks']}" if self.bad_blocks is not None else "Taranmadı"

        print("\n" + "=" * 60)
        print(f"  MODEL       : {info['model']}")
        print(f"  ID          : {self.chip_id}")
        print(f"  HIZ         : {self.speed/1e6:.1f} MHz")
        print(f"  BOYUT       : {total_mb} MB")
        print(f"  SAYFA       : {info['page_size']} B + {info['oob_size']} B OOB")
        print(f"  BLOK        : {info['block_size_kb']} KB ({ppb} sayfa/blok)")
        print(f"  BLOK SAYISI : {info['total_blocks']}")
        print(f"  YAZMA KOR.  : {prot_str}")
        print(f"  ONFI        : {onfi_str}")
        print(f"  BAD BLOCK   : {bad_str}")
        print("=" * 60)

    @staticmethod
    def _progress(current, total, start_time, label, unit='B'):
        elapsed = time.time() - start_time
        percent = (current / total * 100) if total > 0 else 100.0
        if unit == 'B' and elapsed > 0:
            speed_str = f"{(current / 1024) / elapsed:8.2f} KB/s"
        elif unit in ('sayfa', 'blok') and elapsed > 0:
            speed_str = f"{current / elapsed:8.2f} {unit}/s"
        else:
            speed_str = "N/A"
        bar_len = 25
        filled = int(bar_len * current // total) if total > 0 else bar_len
        bar = '█' * filled + ' ' * (bar_len - filled)
        sys.stdout.write(
            f"\r{label} |{bar}| %{percent:5.1f} | {speed_str} | {current}/{total} {unit}"
        )
        sys.stdout.flush()

    def input_range(self, prompt, max_val, unit_name):
        print(f"\n{prompt} (0 - {max_val-1} {unit_name}, '*' veya boş = tümü)")
        s = input("Başlangıç (varsayılan 0): ").strip()
        s = 0 if s in ("", "*") else int(s)
        e = input("Bitiş (varsayılan son): ").strip()
        e = max_val - 1 if e in ("", "*") else int(e)
        if s < 0: s = 0
        if e >= max_val: e = max_val - 1
        if s > e:
            s, e = e, s
            print("Başlangıç > Bitiş, yer değiştirildi.")
        return s, e

    # ------------------------------------------------------------------ #
    #  Ana menü                                                           #
    # ------------------------------------------------------------------ #

    def main_menu(self):
        # 1. Hız seçimi
        self.select_speed()
        # 2. Çip tanıma
        self.detect_chip()
        # 3. ONFI kontrolü
        self.check_onfi()
        # 4. Bad block taraması
        self.scan_bad_blocks()
        # 5. Header yazdır
        self.print_header()

        while True:
            print("\n--- ANA MENÜ ---")
            print("1. OKU    (sayfa aralığı)")
            print("2. YAZ    (dosyadan)")
            print("3. SİL    (blok aralığı)")
            print("4. BAD BLOCK TARAMASINI YENİLE")
            if self.protected:
                print("5. YAZMA KORUMASINI KALDIR")
                print("6. ÇIKIŞ")
                valid = ['1', '2', '3', '4', '5', '6']
            else:
                print("5. ÇIKIŞ")
                valid = ['1', '2', '3', '4', '5']

            choice = input("Seçiminiz: ").strip()
            if choice not in valid:
                print("Geçersiz seçim!")
                continue

            if choice == '1':
                fname = input("Çıktı dosya adı: ").strip()
                if not fname:
                    continue
                ps = self.chip_info['page_size']
                total_pages = self.chip_info['total_blocks'] * (self.chip_info['block_size_kb'] * 1024 // ps)
                s, e = self.input_range("Sayfa aralığı", total_pages, "sayfa")
                self.read_pages(s, e, fname)

            elif choice == '2':
                fname = input("Kaynak dosya adı: ").strip()
                if not os.path.exists(fname):
                    print("Dosya bulunamadı.")
                    continue
                ps = self.chip_info['page_size']
                total_pages = self.chip_info['total_blocks'] * (self.chip_info['block_size_kb'] * 1024 // ps)
                start = int(input(f"Başlangıç sayfası (0-{total_pages-1}): ") or 0)
                erase = input("Önce blokları silinsin mi? (e/h): ").lower() == 'e'
                self.write_pages(start, fname, erase_first=erase)

            elif choice == '3':
                total_blocks = self.chip_info['total_blocks']
                s, e = self.input_range("Blok aralığı", total_blocks, "blok")
                self.erase_blocks(s, e)

            elif choice == '4':
                self.scan_bad_blocks()
                self.print_header()

            elif choice == '5' and self.protected:
                self.nand_unlock_all()
                self.print_header()

            elif (choice == '5' and not self.protected) or choice == '6':
                self.close_spi()
                print("Çıkış yapılıyor.")
                break


if __name__ == "__main__":
    tool = SPINandTool()
    tool.main_menu()
