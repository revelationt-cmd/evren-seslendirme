"""Üretilen sesi ASR'den geçirip senaryoyla karşılaştırır, kelime hata oranını (WER) raporlar.

seslendir.py'nin yazdığı <ses>.parcalar.json dosyası senaryo olarak kullanılır. Her parça
qwen3-asr-1.7b ile yazıya dökülür ve senaryodaki kelimelerle hizalanır. Sayılar ve özel adlar
ayrı raporlanır; Türkçe seslendirmede hatanın çoğu bu iki grupta çıkıyor.

Adil karşılaştırma için iki taraf da turkce-normalize ile okunuşa çevrilir (ASR "1923" yazar,
senaryoda "bin dokuz yüz yirmi üç" olabilir). Paket kurulu değilse karşılaştırma yine yapılır
ama rakamla yazılmış sayılar hata sayılabilir; ekranda uyarı çıkar.

ASR sonuçları <ses>.asr.json dosyasına yazılır, ikinci çalıştırmada API'ye yeniden gidilmez.

Örnek:
    python karsilastir.py cikti/ornek.mp3
    python karsilastir.py cikti/ornek.mp3 --ozel Evren,Remotion --yeniden
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from altyazi import yaziya_dok

SAYI_KELIMELERI = {
    "sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz",
    "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan",
    "yüz", "bin", "milyon", "milyar", "trilyon", "buçuk", "yarım", "virgül", "çeyrek",
}
_KELIME = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")


def kucuk(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def kelimeler(metin: str) -> list[str]:
    """Küçük harfe çevirir, noktalamayı ve kesmeyi atar: "Türkiye'deki" -> "türkiyedeki"."""
    return [kucuk(k).replace("'", "").replace("’", "") for k in _KELIME.findall(metin)]


def ozel_kokler(metin: str, ekler: list[str]) -> set[str]:
    """Cümle başı dışında büyük harfle başlayan kelimelerin kökleri (kesmeden önceki kısım)."""
    kokler = {kucuk(e) for e in ekler if e}
    cumle_basi = True
    for k in re.findall(r"[^\W_]+(?:['’][^\W_]+)?|[.!?]", metin):
        if k in ".!?":
            cumle_basi = True
            continue
        if k[0].isupper() and not cumle_basi:
            kokler.add(kucuk(re.split(r"['’]", k)[0]))
        cumle_basi = False
    return {k for k in kokler if len(k) >= 3}


def hizala(ref: list[str], hyp: list[str]) -> list[tuple[str, str | None, str | None]]:
    """Levenshtein hizalaması: (işlem, senaryo, duyulan) listesi. İşlem: = D S E (eşit/değişen/silinen/eklenen)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    yol, i, j = [], n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            yol.append(("=" if ref[i - 1] == hyp[j - 1] else "D", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            yol.append(("S", ref[i - 1], None))
            i -= 1
        else:
            yol.append(("E", None, hyp[j - 1]))
            j -= 1
    return yol[::-1]


def tur(kelime: str, kokler: set[str]) -> str:
    if kelime.isdigit() or kelime in SAYI_KELIMELERI:
        return "sayi"
    if any(kelime.startswith(k) for k in kokler):
        return "ozel"
    return "diger"


def asr_sonuclari(ses: Path, parcalar: list[dict], dil: str, yeniden: bool) -> list[str]:
    onbellek = ses.with_suffix(".asr.json")
    eski = {}
    if onbellek.is_file() and not yeniden:
        eski = {(r["i"], r["metin"]): r["duyulan"] for r in json.loads(onbellek.read_text(encoding="utf-8"))}
    duyulanlar = []
    with tempfile.TemporaryDirectory() as td:
        for p in parcalar:
            anahtar = (p["i"], p["metin"])
            if anahtar in eski:
                duyulanlar.append(eski[anahtar])
                continue
            parca = Path(td) / f"{p['i']}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{p['startMs'] / 1000}", "-to",
                            f"{p['endMs'] / 1000}", "-i", str(ses), "-ar", "16000", "-ac", "1", str(parca)], check=True)
            duyulanlar.append((yaziya_dok(parca.read_bytes(), dil).get("text") or "").strip())
            print(f"  ASR {p['i']:02d}: {duyulanlar[-1][:80]}", flush=True)
    onbellek.write_text(json.dumps([{"i": p["i"], "metin": p["metin"], "duyulan": d}
                                    for p, d in zip(parcalar, duyulanlar)], ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return duyulanlar


def main() -> None:
    ap = argparse.ArgumentParser(description="Seslendirmeyi ASR ile senaryoya karşı ölç (WER)")
    ap.add_argument("ses", type=Path, help="seslendir.py çıktısı (yanında .parcalar.json olmalı)")
    ap.add_argument("--dil", default="tr")
    ap.add_argument("--ozel", default="", help="Özel ad sayılacak ek kelimeler, virgülle: Evren,Remotion")
    ap.add_argument("--yeniden", action="store_true", help="ASR önbelleğini yok say, yeniden yazıya dök")
    ap.add_argument("--rapor", type=Path, help="JSON rapor yolu (varsayılan <ses>.wer.json)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler bozulmasın

    parca_json = a.ses.with_suffix(".parcalar.json")
    if not parca_json.is_file():
        sys.exit(f"{parca_json.name} bulunamadı. Bu betik seslendir.py çıktısıyla çalışır.")
    parcalar = json.loads(parca_json.read_text(encoding="utf-8"))

    try:
        from turkce_normalize import normalize
        okunur = lambda m: normalize(m, cografi=False)
    except ImportError:
        okunur = lambda m: m
        print("! turkce-normalize kurulu değil: rakamla yazılmış sayılar hata sayılabilir "
              "(pip install turkce-normalize).", file=sys.stderr)

    duyulanlar = asr_sonuclari(a.ses, parcalar, a.dil, a.yeniden)
    ekler = [e.strip() for e in a.ozel.split(",")]
    sayac = {t: {"kelime": 0, "hata": 0} for t in ("sayi", "ozel", "diger")}
    eklenen, hatalar = 0, []

    for p, duyulan in zip(parcalar, duyulanlar):
        kokler = ozel_kokler(p["metin"], ekler)
        ref = kelimeler(okunur(p.get("okunan") or p["metin"]))
        hyp = kelimeler(okunur(duyulan))
        for islem, r, h in hizala(ref, hyp):
            if islem == "E":
                eklenen += 1
                hatalar.append({"i": p["i"], "tur": "eklenen", "senaryo": None, "duyulan": h})
                continue
            t = tur(r, kokler)
            sayac[t]["kelime"] += 1
            if islem != "=":
                sayac[t]["hata"] += 1
                hatalar.append({"i": p["i"], "tur": t, "senaryo": r, "duyulan": h})

    toplam = sum(s["kelime"] for s in sayac.values())
    hata = sum(s["hata"] for s in sayac.values()) + eklenen
    wer = hata / toplam if toplam else 0.0
    oran = lambda s: s["hata"] / s["kelime"] if s["kelime"] else 0.0

    print(f"\nWER: %{wer * 100:.1f}  ({hata} hata / {toplam} kelime, {eklenen} fazladan kelime)")
    for t, ad in (("sayi", "Sayılar"), ("ozel", "Özel adlar"), ("diger", "Diğer")):
        print(f"  {ad:11s} %{oran(sayac[t]) * 100:5.1f}  ({sayac[t]['hata']}/{sayac[t]['kelime']})")
    if hatalar:
        print("\nHatalar (senaryo -> duyulan):")
        for h in hatalar:
            print(f"  [{h['i']:02d}] {h['tur']:7s} {h['senaryo'] or '-'} -> {h['duyulan'] or '-'}")

    rapor = a.rapor or a.ses.with_suffix(".wer.json")
    rapor.write_text(json.dumps({
        "wer": round(wer, 4), "kelime": toplam, "hata": hata, "eklenen": eklenen,
        "turler": {t: {**s, "oran": round(oran(s), 4)} for t, s in sayac.items()},
        "hatalar": hatalar,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRapor -> {rapor}")


if __name__ == "__main__":
    main()
