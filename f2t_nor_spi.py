#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# spinor-tool.py  —  Raspberry Pi için SPI NOR programlama aracı
#
# NAND aracıyla aynı tasarım prensipleri:
#   - Otomatik optimum SPI hızı algılama ve seçme
#   - JSON veritabanından çip tanıma, yoksa kullanıcıdan bilgi alıp kaydetme
#   - Yazma koruması kontrolü ve kaldırma
#   - Okuma, yazma, silme (sektör/tüm çip), doğrulama, hexdump
#   - Büyük SPI transferlerini parçalama

import spidev
import os
import sys
import time
import json

_SPI_MAX_XFER = 4096
_SPI_SAFE_DATA = _SPI_MAX_XFER - 8


class SPINorTool:
    def __init__(self):
        self.spi = spidev.SpiDev()
        self.db_path = 'nor_spi.json'
        self.chip_db = self.load_db()
        self.chip_info = None
        self.chip_id = None
        self.speed = 8_000_000
        self.protected = False

    # ------------------------------------------------------------------ #
    #  Veritabanı işlemleri                                               #
    # ------------------------------------------------------------------ #

    def load_db(self):
        """Veritabanını yükler, yoksa/bozuksa boş bir yapıyla devam eder."""
        if not os.path.exists(self.db_path):
            default_db = {"nor": {}}
            with open(self.db_path, 'w') as f:
                json.dump(default_db, f, indent=2)
            print("[*] Yeni boş NOR veritabanı oluşturuldu.")
            return default_db

        try:
            with open(self.db_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Veritabanı okunamadı ({e}). Bozuk dosya yedekleniyor...")
            backup_name = self.db_path + ".bak"
            try:
                os.rename(self.db_path, backup_name)
                print(f"    Eski dosya '{backup_name}' olarak saklandı.")
            except Exception:
                pass
            default_db = {"nor": {}}
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
        """Tek seferde gönderilemeyen verileri parçalar."""
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
        test_speeds = [500_000, 1_000_000, 2_000_000, 4_000_000,
                       8_000_000, 16_000_000, 32_000_000]
        working = []
        print("[*] Çalışma frekansları taranıyor...")
        for speed in test_speeds:
            try:
                self.open_spi(speed)
                resp = self.spi.xfer2([0x9F, 0x00, 0x00, 0x00])
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
        self.open_spi(self.speed)
        raw = self.spi.xfer2([0x9F] + [0x00]*3)
        chip_id = "0x" + "".join(f"{x:02X}" for x in raw[1:4])
        if "nor" in self.chip_db and chip_id in self.chip_db["nor"]:
            self.chip_info = self.chip_db["nor"][chip_id]
            self.chip_id = chip_id
            print(f"[+] Çip tanındı: {self.chip_info['model']} (ID: {chip_id})")
            return True
        else:
            print(f"[!] {chip_id} ID'li çip veritabanında bulunamadı.")
            print("Lütfen aşağıdaki bilgileri girin:")
            model = input("Model adı: ").strip()
            page_size = int(input("Sayfa boyutu (byte, örn: 256): "))
            sector_size_kb = int(input("Sektör boyutu (KB, örn: 4/32/64): "))
            total_mb = int(input("Toplam kapasite (MB): "))
            self.chip_info = {
                "model": model,
                "page_size": page_size,
                "sector_size_kb": sector_size_kb,
                "total_mb": total_mb
            }
            if "nor" not in self.chip_db:
                self.chip_db["nor"] = {}
            self.chip_db["nor"][chip_id] = self.chip_info
            self.save_db()
            print("[+] Veritabanı güncellendi. Program yeniden başlatılıyor...")
            self.close_spi()
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # ------------------------------------------------------------------ #
    #  NOR durum ve koruma                                                #
    # ------------------------------------------------------------------ #

    def nor_read_status(self):
        """Status Register oku (0x05)."""
        return self.spi.xfer2([0x05, 0x00])[1]

    def nor_write_enable(self):
        self.spi.xfer2([0x06])

    def nor_wait_busy(self):
        """WIP (Write In Progress) biti 0 olana kadar bekle."""
        while True:
            if not (self.nor_read_status() & 0x01):
                break
            time.sleep(0.001)
        time.sleep(0.0001)

    def nor_check_protection(self):
        """BP bitlerini oku ve koruma durumunu yorumla."""
        sr = self.nor_read_status()
        bp = (sr >> 2) & 0x1F           # NOR'larda genelde BP0-BP4 olabilir, maskeyi geniş tuttuk
        srp = (sr >> 7) & 0x01
        return bp != 0, bool(srp)

    def nor_unlock(self):
        """Write Enable sonrası Status Register'ı yazarak BP bitlerini sıfırla."""
        self.nor_write_enable()
        # Status Register'ın sadece BP bitlerini sıfırla, diğer bitleri koru.
        # Bazı çipler için Write Status Register komutu 0x01, bazıları 0x31
        # Biz standart 0x01 kullanıyoruz.
        cur_sr = self.nor_read_status()
        new_sr = cur_sr & 0x03          # sadece WIP ve WEL korunur, BP'ler sıfırlanır
        self.spi.xfer2([0x01, new_sr])
        self.nor_wait_busy()
        bp, _ = self.nor_check_protection()
        if bp:
            print("[!] Koruma hâlâ aktif (WP# pini HIGH mı?).")
        else:
            print("[+] Yazma koruması kaldırıldı.")

    # ------------------------------------------------------------------ #
    #  NOR okuma / yazma / silme                                          #
    # ------------------------------------------------------------------ #

    def nor_read(self, addr, length):
        """Adresten itibaren 'length' bayt oku (0x03). 24 bit adres kullanılır."""
        result = bytearray()
        while length > 0:
            chunk = min(_SPI_SAFE_DATA, length)
            # Komut + 3 byte adres
            cmd = [0x03, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF]
            rx = self._xfer(cmd + [0x00] * chunk)
            result.extend(rx[4:4+chunk])   # ilk 4 byte komut+adres
            addr += chunk
            length -= chunk
        return bytes(result)

    def nor_write_page(self, addr, data):
        """Sayfa programla (0x02). Sayfa boyutu chip_info['page_size'] ile uyumlu olmalı."""
        ps = self.chip_info['page_size']
        if len(data) > ps:
            raise ValueError("Veri sayfa boyutundan büyük olamaz.")
        self.nor_write_enable()
        cmd = [0x02, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF]
        self._xfer(cmd + list(data))
        self.nor_wait_busy()

    def nor_erase_sector(self, addr):
        """Sektör sil (komut chip_info'daki sector_size_kb'ye göre seçilir)."""
        sector_kb = self.chip_info['sector_size_kb']
        if sector_kb == 4:
            cmd = 0x20
        elif sector_kb == 32:
            cmd = 0x52
        elif sector_kb == 64:
            cmd = 0xD8
        else:
            raise ValueError(f"Bilinmeyen sektör boyutu: {sector_kb} KB")
        self.nor_write_enable()
        self.spi.xfer2([cmd, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])
        self.nor_wait_busy()

    def nor_erase_chip(self):
        """Tüm çipi sil (0xC7)."""
        print("[*] Tüm çip siliniyor...")
        self.nor_write_enable()
        self.spi.xfer2([0xC7])
        self.nor_wait_busy()
        print("[+] Silme tamamlandı.")

    def nor_erase_range(self, start_addr, end_addr):
        """Başlangıç ve bitiş adres arasındaki tüm sektörleri sil."""
        sector_size = self.chip_info['sector_size_kb'] * 1024
        start_sec = start_addr // sector_size
        end_sec = (end_addr + sector_size - 1) // sector_size
        total = end_sec - start_sec
        print(f"[*] Sektör silme: {start_sec} -> {end_sec-1} ({total} sektör)")
        start_t = time.time()
        for i, sec in enumerate(range(start_sec, end_sec)):
            addr = sec * sector_size
            self.nor_erase_sector(addr)
            self._progress(i+1, total, start_t, "SİLME", "sektör")
        print()

    # ------------------------------------------------------------------ #
    #  Üst seviye işlemler (menüden çağrılan)                             #
    # ------------------------------------------------------------------ #

    def read_to_file(self, filename, start_addr, length):
        """Bellek aralığını dosyaya oku."""
        print(f"[*] Okuma: 0x{start_addr:06X} - 0x{start_addr+length-1:06X} ({length} bayt)")
        start_t = time.time()
        total = length
        with open(filename, 'wb') as f:
            addr = start_addr
            remaining = length
            while remaining > 0:
                chunk = min(_SPI_SAFE_DATA, remaining)
                data = self.nor_read(addr, chunk)
                f.write(data)
                addr += chunk
                remaining -= chunk
                self._progress(total - remaining, total, start_t, "OKUMA", "B")
        print()

    def write_from_file(self, filename, start_addr):
        """Dosyayı NOR belleğe yaz. Gerekirse önce sil."""
        if not os.path.exists(filename):
            print("Dosya bulunamadı.")
            return
        file_size = os.path.getsize(filename)
        chip_size = self.chip_info['total_mb'] * 1024 * 1024
        if start_addr + file_size > chip_size:
            print("HATA: Dosya çip kapasitesini aşıyor.")
            return

        ps = self.chip_info['page_size']
        print(f"[*] Yazma: başlangıç 0x{start_addr:06X}, dosya {filename}")
        start_t = time.time()
        with open(filename, 'rb') as f:
            addr = start_addr
            while True:
                data = f.read(ps)
                if not data:
                    break
                # Sayfa hizalama gerekmezse bile, yine de sayfa sınırında yazmak iyidir.
                self.nor_write_page(addr, data)
                addr += len(data)
                self._progress(f.tell(), file_size, start_t, "YAZMA", "B")
        print()

    def verify_file(self, filename, start_addr):
        """Dosyayı NOR bellek ile karşılaştır."""
        if not os.path.exists(filename):
            print("Dosya bulunamadı.")
            return
        file_size = os.path.getsize(filename)
        print(f"[*] Doğrulama: 0x{start_addr:06X}, dosya {filename}")
        start_t = time.time()
        with open(filename, 'rb') as f:
            addr = start_addr
            while True:
                file_chunk = f.read(_SPI_SAFE_DATA)
                if not file_chunk:
                    break
                nor_chunk = self.nor_read(addr, len(file_chunk))
                if nor_chunk != file_chunk:
                    # Farklılık bulundu
                    for i, (a, b) in enumerate(zip(nor_chunk, file_chunk)):
                        if a != b:
                            print(f"\n[!] Eşleşmeyen veri @ 0x{addr+i:06X}: NOR=0x{a:02X}, dosya=0x{b:02X}")
                            return
                addr += len(file_chunk)
                self._progress(addr - start_addr, file_size, start_t, "DOĞRULAMA", "B")
        print("\n[+] Doğrulama başarılı, veriler birebir aynı.")

    def hexdump(self, start_addr, length):
        """Adresten itibaren hexdump yazdır."""
        print(f"\nHexdump: 0x{start_addr:06X} - 0x{start_addr+length-1:06X} ({length} bayt)")
        data = self.nor_read(start_addr, length)
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_str = ' '.join(f'{x:02X}' for x in chunk)
            asc_str = ''.join(chr(x) if 32 <= x < 127 else '.' for x in chunk)
            print(f"  {start_addr+i:06X}: {hex_str:<48}  {asc_str}")

    # ------------------------------------------------------------------ #
    #  Header ve yardımcılar                                              #
    # ------------------------------------------------------------------ #

    def print_header(self):
        info = self.chip_info
        total_kb = info['total_mb'] * 1024
        sector_kb = info['sector_size_kb']
        total_sectors = total_kb // sector_kb
        bp, srp = self.nor_check_protection()
        self.protected = bp
        prot_str = "EVET" if bp else "HAYIR"
        if srp:
            prot_str += " (SRP kilitli)"
        print("\n" + "=" * 60)
        print(f"  MODEL       : {info['model']}")
        print(f"  ID          : {self.chip_id}")
        print(f"  HIZ         : {self.speed/1e6:.1f} MHz")
        print(f"  BOYUT       : {info['total_mb']} MB ({total_kb} KB)")
        print(f"  SAYFA       : {info['page_size']} byte")
        print(f"  SEKTÖR      : {sector_kb} KB ({total_sectors} sektör)")
        print(f"  YAZMA KOR.  : {prot_str}")
        print("=" * 60)

    @staticmethod
    def _progress(current, total, start_time, label, unit='B'):
        elapsed = time.time() - start_time
        percent = (current / total * 100) if total > 0 else 100.0
        if unit == 'B' and elapsed > 0:
            speed_str = f"{(current / 1024) / elapsed:8.2f} KB/s"
        elif unit == 'sektör' and elapsed > 0:
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

    # ------------------------------------------------------------------ #
    #  Ana menü                                                           #
    # ------------------------------------------------------------------ #

    def main_menu(self):
        self.select_speed()
        self.detect_chip()
        self.print_header()

        while True:
            print("\n--- ANA MENÜ ---")
            print("1. OKU       (dosyaya)")
            print("2. YAZ       (dosyadan)")
            print("3. DOĞRULA   (dosya ile)")
            print("4. SİL       (sektör aralığı / tüm çip)")
            print("5. HEXDUMP   (ekrana)")
            if self.protected:
                print("6. KORUMA KALDIR")
                print("7. ÇIKIŞ")
                valid = ['1', '2', '3', '4', '5', '6', '7']
            else:
                print("6. ÇIKIŞ")
                valid = ['1', '2', '3', '4', '5', '6']

            choice = input("Seçiminiz: ").strip()
            if choice not in valid:
                print("Geçersiz seçim!")
                continue

            if choice == '1':
                fname = input("Çıktı dosya adı: ").strip()
                if not fname: continue
                chip_size = self.chip_info['total_mb'] * 1024 * 1024
                print(f"Adres aralığı (0 - 0x{chip_size-1:06X})")
                start = int(input("Başlangıç adresi (hex veya dec, varsayılan 0): ").strip() or "0", 0)
                length = int(input("Okunacak bayt sayısı (varsayılan tümü): ").strip() or str(chip_size - start))
                if start + length > chip_size:
                    print("HATA: Çip kapasitesini aşıyor.")
                    continue
                self.read_to_file(fname, start, length)

            elif choice == '2':
                fname = input("Kaynak dosya adı: ").strip()
                if not os.path.exists(fname): continue
                chip_size = self.chip_info['total_mb'] * 1024 * 1024
                start = int(input(f"Başlangıç adresi (hex/dec, varsayılan 0): ").strip() or "0", 0)
                erase = input("Önce ilgili bölgeyi silinsin mi? (e/h): ").lower() == 'e'
                if erase:
                    file_size = os.path.getsize(fname)
                    end_addr = start + file_size - 1
                    self.nor_erase_range(start, end_addr)
                self.write_from_file(fname, start)

            elif choice == '3':
                fname = input("Doğrulanacak dosya: ").strip()
                if not os.path.exists(fname): continue
                start = int(input("Başlangıç adresi (varsayılan 0): ").strip() or "0", 0)
                self.verify_file(fname, start)

            elif choice == '4':
                chip_size = self.chip_info['total_mb'] * 1024 * 1024
                print("Silme türü:")
                print("  a) Sektör aralığı")
                print("  b) Tüm çip")
                sub = input("Seçiminiz: ").strip().lower()
                if sub == 'a':
                    print(f"Adres aralığı (0 - 0x{chip_size-1:06X})")
                    start = int(input("Başlangıç: ").strip(), 0)
                    end   = int(input("Bitiş: ").strip(), 0)
                    if start < 0 or end >= chip_size or start > end:
                        print("Geçersiz aralık.")
                        continue
                    self.nor_erase_range(start, end)
                elif sub == 'b':
                    if input("Tüm çip silinecek! Emin misiniz? (e/h): ").lower() == 'e':
                        self.nor_erase_chip()
                else:
                    print("Geçersiz seçim.")

            elif choice == '5':
                chip_size = self.chip_info['total_mb'] * 1024 * 1024
                print(f"Adres aralığı (0 - 0x{chip_size-1:06X})")
                start = int(input("Başlangıç adresi: ").strip(), 0)
                length = int(input("Gösterilecek bayt: ").strip())
                if start + length > chip_size:
                    print("HATA: Çip kapasitesini aşıyor.")
                    continue
                self.hexdump(start, length)

            elif choice == '6' and self.protected:
                self.nor_unlock()
                self.print_header()

            elif (choice == '6' and not self.protected) or choice == '7':
                self.close_spi()
                print("Çıkış yapılıyor.")
                break


if __name__ == "__main__":
    tool = SPINorTool()
    tool.main_menu()
