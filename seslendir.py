"""Metni EVREN voxcpm2 modeliyle Türkçe seslendirir.

Girdi metin dosyasında her boş olmayan satır bir parçadır. İsteğe bağlı biçim:
    [sahne] Metin...            -> sahne adı
    [sahne|1.2] Metin...        -> parçadan sonra 1.2 sn sessizlik
`#` ile başlayan satırlar yok sayılır.

Çıktılar:
    <cikti>.mp3                 birleştirilmiş, ses seviyesi normalize edilmiş seslendirme
    <cikti>.parcalar.json       her parçanın başlangıç/bitiş ms'i (Remotion sahne zamanlaması için)

İsteğe bağlı metin normalizasyonu (--normalize): rakam, tarih, saat ve kısaltmalar modele gitmeden
Türkçe okunuşa çevrilir ("14:30'da" -> "on dört otuzda"). turkce-normalize paketini kullanır:
    pip install turkce-normalize

Örnek:
    python seslendir.py ornek/metin.txt --ses deniz --cikti ../public/evren-ornek.mp3
    python seslendir.py ornek/ham_metin.txt --normalize --telaffuz ornek/telaffuz.json --hiz 0.96
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from evren_api import istek

SESLER = ("deniz", "ece", "emre", "kaan")
SR = 48000
SATIR = re.compile(r"^\[(?P<sahne>[^\]|]+)(?:\|(?P<ara>[\d.]+))?\]\s*(?P<metin>.+)$")


def oku(yol: Path, varsayilan_ara: float) -> list[dict]:
    parcalar = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        m = SATIR.match(satir)
        if m:
            parcalar.append({"sahne": m["sahne"].strip(), "metin": m["metin"].strip(),
                             "ara": float(m["ara"]) if m["ara"] else varsayilan_ara})
        else:
            parcalar.append({"sahne": f"p{len(parcalar):02d}", "metin": satir, "ara": varsayilan_ara})
    for p in parcalar:
        if len(p["metin"]) > 4096:
            sys.exit(f"'{p['sahne']}' parçası 4096 karakteri aşıyor; satırı bölün.")
    return parcalar


def normalizer(telaffuz_yolu: Path | None):
    """turkce-normalize ile metni okunur hale getiren fonksiyon döndürür."""
    try:
        from turkce_normalize import VARSAYILAN_SOZLUK, normalize, sozluk_birlestir
    except ImportError:
        sys.exit("--normalize için turkce-normalize paketi gerekli: pip install turkce-normalize")
    sozluk = VARSAYILAN_SOZLUK
    if telaffuz_yolu:
        ek = json.loads(telaffuz_yolu.read_text(encoding="utf-8"))
        sozluk = sozluk_birlestir(VARSAYILAN_SOZLUK, ek)
    return lambda metin: normalize(metin, telaffuz=sozluk, cografi=False)


def seslendir(metin: str, ses: str, tarif: str | None, hiz: float, hedef: Path) -> None:
    govde = {"model": "voxcpm2", "input": metin, "voice": ses, "response_format": "wav"}
    if tarif:
        govde["instructions"] = tarif
    if hiz != 1.0:
        govde["speed"] = hiz
    veri, basliklar = istek("/audio/speech", json_govde=govde)
    if not veri.startswith(b"RIFF"):
        sys.exit(f"Beklenen WAV gelmedi ({basliklar.get('Content-Type')}): {veri[:200]!r}")
    hedef.write_bytes(veri)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def sure(p: Path) -> float:
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(o.stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="EVREN voxcpm2 ile Türkçe seslendirme")
    ap.add_argument("metin", type=Path, help="Metin dosyası (satır başına bir parça)")
    ap.add_argument("--ses", default="deniz", choices=SESLER)
    ap.add_argument("--tarif", help="İngilizce ses tarifi (instructions); verilirse hazır sesin yerine geçer")
    ap.add_argument("--cikti", type=Path, default=Path("cikti/seslendirme.mp3"))
    ap.add_argument("--ara", type=float, default=0.5, help="Parçalar arası varsayılan sessizlik (sn)")
    ap.add_argument("--bas", type=float, default=0.5, help="Baştaki sessizlik (sn)")
    ap.add_argument("--hiz", type=float, default=1.0,
                    help="Konuşma hızı (speed). 1.0 normal, 0.9 = %%10 yavaş")
    ap.add_argument("--normalize", action="store_true",
                    help="Rakam, tarih, saat ve kısaltmaları Türkçe okunuşa çevir (turkce-normalize gerekir)")
    ap.add_argument("--telaffuz", type=Path,
                    help="Ek telaffuz sözlüğü (JSON: {\"Remotion\": \"Rimoşın\"}); --normalize ile birlikte")
    a = ap.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg ve ffprobe PATH üzerinde olmalı.")
    if not 0.25 <= a.hiz <= 4.0:
        sys.exit("--hiz 0.25 ile 4.0 arasında olmalı.")
    if a.telaffuz and not a.normalize:
        sys.exit("--telaffuz yalnız --normalize ile kullanılır.")

    parcalar = oku(a.metin, a.ara)
    if a.normalize:
        okunur = normalizer(a.telaffuz)
        for p in parcalar:
            p["okunan"] = okunur(p["metin"])
            if len(p["okunan"]) > 4096:
                sys.exit(f"'{p['sahne']}' parçası normalizasyondan sonra 4096 karakteri aşıyor; satırı bölün.")
    a.cikti.parent.mkdir(parents=True, exist_ok=True)
    gecici = a.cikti.parent / f".{a.cikti.stem}-parcalar"
    gecici.mkdir(exist_ok=True)

    sessiz = lambda ad, sn: (ffmpeg("-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", f"{sn}", str(gecici / ad)), gecici / ad)[1]
    liste = [sessiz("bas.wav", a.bas)] if a.bas > 0 else []
    bilgi, t = [], a.bas

    for i, p in enumerate(parcalar):
        # Aynı metin+ses tekrar istenirse API'ye yeniden gitme (kota dostu önbellek)
        okunan = p.get("okunan", p["metin"])
        hiz_imza = "" if a.hiz == 1.0 else f"|{a.hiz}"  # hız verilmezse eski önbellek geçerli kalır
        imza = hashlib.sha1(f"{a.ses}|{a.tarif}|{okunan}{hiz_imza}".encode("utf-8")).hexdigest()[:12]
        ham = gecici / f"{imza}.wav"
        if not ham.exists():
            seslendir(okunan, a.ses, a.tarif, a.hiz, ham)
        norm = gecici / f"n{i:03d}.wav"
        ffmpeg("-i", str(ham), "-ar", str(SR), "-ac", "1", str(norm))
        d = sure(norm)
        kayit = {"i": i, "sahne": p["sahne"], "metin": p["metin"],
                 "startMs": round(t * 1000), "endMs": round((t + d) * 1000)}
        if okunan != p["metin"]:
            kayit["okunan"] = okunan  # modele giden metin; altyazıda yine senaryo (metin) kullanılır
        bilgi.append(kayit)
        liste.append(norm)
        if p["ara"] > 0:
            liste.append(sessiz(f"s{i:03d}.wav", p["ara"]))
        t += d + p["ara"]
        print(f"{i:02d} {p['sahne']:12s} {d:5.1f} sn", flush=True)

    lst = gecici / "liste.txt"
    lst.write_text("".join(f"file '{x.resolve().as_posix()}'\n" for x in liste), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-af", "loudnorm=I=-16:TP=-1.5",
           "-ar", "44100", "-b:a", "192k", str(a.cikti))
    json_yol = a.cikti.with_suffix(".parcalar.json")
    json_yol.write_text(json.dumps(bilgi, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Toplam {t:.1f} sn -> {a.cikti}\nZamanlama -> {json_yol}")


if __name__ == "__main__":
    main()
