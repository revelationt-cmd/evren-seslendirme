"""Ses dosyasını EVREN qwen3-asr-1.7b ile yazıya döker, Remotion'ın Caption biçiminde JSON üretir.

ASR modeli istek başına ~30 sn ses kabul eder. Betik sesi sessizlik noktalarından
en fazla --pencere saniyelik parçalara böler, her parçayı ayrı gönderir ve zamanları birleştirir.

Model kelime zamanı döndürürse onlar kullanılır; döndürmezse kelime zamanları,
parça içinde harf sayısına göre orantılı dağıtılarak YAKLAŞIK hesaplanır (çıktıda "yaklasik": true).
Kesin kelime senkronu gerekiyorsa projedeki yerel Whisper (`npm run transcribe`) daha uygundur.

Örnek:
    python altyazi.py ../public/evren-ornek.mp3
    -> ../public/evren-ornek.captions.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from evren_api import cok_parcali, istek

MODEL = "qwen3-asr-1.7b"


def sure(p: Path) -> float:
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(o.stdout.strip())


def sessizlikler(p: Path) -> list[float]:
    """Sessizlik orta noktalarını (sn) döndürür."""
    o = subprocess.run(["ffmpeg", "-v", "info", "-i", str(p), "-af", "silencedetect=n=-35dB:d=0.25", "-f", "null", "-"],
                       capture_output=True, text=True)
    bas = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", o.stderr)]
    son = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", o.stderr)]
    return [(b + s) / 2 for b, s in zip(bas, son)]


def kesimler(toplam: float, orta: list[float], pencere: float) -> list[tuple[float, float]]:
    araliklar, bas = [], 0.0
    while toplam - bas > pencere:
        adaylar = [m for m in orta if bas + 3 < m <= bas + pencere]
        kes = adaylar[-1] if adaylar else bas + pencere  # sessizlik yoksa zorunlu kesim
        araliklar.append((bas, kes))
        bas = kes
    araliklar.append((bas, toplam))
    return araliklar


def yaziya_dok(wav: bytes, dil: str) -> dict:
    # qwen3-asr verbose_json (kelime zamanı) desteklemiyor; düz json yalnız metni döndürür
    govde, tur = cok_parcali(
        {"model": MODEL, "language": dil, "response_format": "json"},
        {"file": ("parca.wav", wav, "audio/wav")},
    )
    veri, _ = istek("/audio/transcriptions", veri=govde, icerik_turu=tur)
    try:
        return json.loads(veri)
    except ValueError:
        return {"text": veri.decode("utf-8", errors="replace")}


def kelimelere(sonuc: dict, bas_ms: int, son_ms: int) -> tuple[list[dict], bool]:
    if sonuc.get("words"):
        return [{"text": " " + w["word"].strip(), "startMs": bas_ms + round(w["start"] * 1000),
                 "endMs": bas_ms + round(w["end"] * 1000)} for w in sonuc["words"]], False
    # Kelime zamanı yok: harf sayısına göre orantılı dağıt
    kelimeler = (sonuc.get("text") or "").split()
    if not kelimeler:
        return [], True
    toplam = sum(len(k) + 1 for k in kelimeler)
    cikti, t = [], float(bas_ms)
    for k in kelimeler:
        d = (son_ms - bas_ms) * (len(k) + 1) / toplam
        cikti.append({"text": " " + k, "startMs": round(t), "endMs": round(t + d)})
        t += d
    return cikti, True


def main() -> None:
    ap = argparse.ArgumentParser(description="EVREN qwen3-asr ile Remotion altyazı JSON'u")
    ap.add_argument("ses", type=Path)
    ap.add_argument("--dil", default="tr")
    ap.add_argument("--pencere", type=float, default=25.0, help="Parça başına en fazla saniye (model sınırı ~30)")
    ap.add_argument("--cikti", type=Path)
    ap.add_argument("--asr-metni", action="store_true",
                    help="Zamanlama dosyası olsa bile altyazıya senaryo yerine ASR'nin duyduğu metni yaz")
    a = ap.parse_args()

    toplam = sure(a.ses)
    # seslendir.py'nin ürettiği zamanlama dosyası varsa her parçayı tam konuşma aralığıyla gönder:
    # sessizlikler dışarıda kalır, yaklaşık kelime zamanları çok daha isabetli olur.
    # Senaryo metni bilindiği için altyazıya o yazılır (özel adlar doğru kalır); ASR çıktısı
    # telaffuz kontrolü için ekrana basılır.
    parca_json = a.ses.with_suffix(".parcalar.json")
    araliklar: list[tuple[float, float, str | None]] = []
    if parca_json.is_file():
        for p in json.loads(parca_json.read_text(encoding="utf-8")):
            b, s = p["startMs"] / 1000, p["endMs"] / 1000
            if s - b <= a.pencere:
                araliklar.append((b, s, None if a.asr_metni else p["metin"]))
                continue
            while s - b > a.pencere:  # model penceresini aşan uzun parçayı böl (senaryo bölünemez, ASR kullanılır)
                araliklar.append((b, b + a.pencere, None))
                b += a.pencere
            araliklar.append((b, s, None))
        print(f"Zamanlama dosyası kullanılıyor: {parca_json.name}")
    else:
        araliklar = [(b, s, None) for b, s in kesimler(toplam, sessizlikler(a.ses), a.pencere)]
    captions, yaklasik_mi = [], False
    with tempfile.TemporaryDirectory() as td:
        for i, (b, s, senaryo) in enumerate(araliklar):
            parca = Path(td) / f"{i}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{b}", "-to", f"{s}", "-i", str(a.ses),
                            "-ar", "16000", "-ac", "1", str(parca)], check=True)
            sonuc = yaziya_dok(parca.read_bytes(), a.dil)
            duyulan = (sonuc.get("text") or "").strip()
            k, yak = kelimelere({"text": senaryo} if senaryo else sonuc, round(b * 1000), round(s * 1000))
            yaklasik_mi |= yak
            captions += k
            print(f"{b:6.1f}-{s:6.1f} sn  ASR: {duyulan[:90]}", flush=True)

    for c in captions:
        c.update({"timestampMs": (c["startMs"] + c["endMs"]) // 2, "confidence": None})
    if captions:
        captions[0]["text"] = captions[0]["text"].lstrip()
    hedef = a.cikti or a.ses.with_suffix(".captions.json")
    hedef.write_text(json.dumps(captions, ensure_ascii=False, indent=1), encoding="utf-8")
    not_ = " (kelime zamanları YAKLAŞIK)" if yaklasik_mi else ""
    print(f"{len(captions)} kelime -> {hedef}{not_}")


if __name__ == "__main__":
    main()
