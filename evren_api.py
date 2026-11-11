"""EVREN LLM API için küçük, bağımlılıksız (yalnız standart kütüphane) istemci.

Anahtar şu sırayla aranır:
  1. EVREN_API_KEY ortam değişkeni
  2. Çalışılan klasördeki veya bu klasörün üstündeki .env dosyasında EVREN_API_KEY=... satırı
Anahtarı asla koda yazmayın, depoya göndermeyin.

Kullanım:
  python evren_api.py durum     # şart onayı, kota ve ses modellerinin durumu
  python evren_api.py sartlar   # şart metnini gösterir, yalnız 'e' yazarsanız kabul eder
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TEMEL = os.environ.get("EVREN_BASE_URL", "https://evren-llmapi.ssyz.org.tr/v1").rstrip("/")


def anahtar() -> str:
    k = os.environ.get("EVREN_API_KEY", "").strip()
    if k:
        return k
    for klasor in [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]:
        env = klasor / ".env"
        if env.is_file():
            for satir in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                satir = satir.strip()
                if satir.startswith("EVREN_API_KEY="):
                    return satir.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("EVREN_API_KEY bulunamadı. .env dosyasına EVREN_API_KEY=evren_llm_... satırını ekleyin.")


class EvrenHatasi(RuntimeError):
    def __init__(self, durum: int, govde: str):
        self.durum = durum
        self.govde = govde
        try:
            self.kod = json.loads(govde).get("error", {}).get("code", "")
        except (ValueError, AttributeError):
            self.kod = ""
        super().__init__(f"HTTP {durum} {self.kod}: {govde[:400]}")


def istek(yol: str, *, veri: bytes | None = None, json_govde: dict | None = None,
          icerik_turu: str | None = None, yontem: str | None = None, deneme: int = 6,
          zaman_asimi: int = 300) -> tuple[bytes, dict]:
    """İstek atar; 429 ve 503'te Retry-After kadar bekleyip yeniden dener. (gövde, başlıklar) döner."""
    basliklar = {"Authorization": f"Bearer {anahtar()}", "User-Agent": "evren-seslendirme/1.0"}
    if json_govde is not None:
        veri = json.dumps(json_govde, ensure_ascii=False).encode("utf-8")
        icerik_turu = "application/json"
    if icerik_turu:
        basliklar["Content-Type"] = icerik_turu
    url = f"{TEMEL}{yol}"
    for i in range(deneme):
        req = urllib.request.Request(url, data=veri, headers=basliklar, method=yontem or ("POST" if veri else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=zaman_asimi) as r:
                return r.read(), dict(r.headers)
        except urllib.error.HTTPError as h:
            govde = h.read().decode("utf-8", errors="replace")
            if h.code in (429, 503) and i < deneme - 1:
                bekle = float(h.headers.get("Retry-After") or 2 ** i)
                print(f"  ! HTTP {h.code}, {bekle:.0f} sn sonra yeniden denenecek", file=sys.stderr)
                time.sleep(min(bekle, 60))
                continue
            hata = EvrenHatasi(h.code, govde)
            if hata.kod == "terms_not_accepted":
                sys.exit("Kullanım şartları henüz kabul edilmemiş. Önce `python evren_api.py sartlar` çalıştırın.")
            raise hata
    raise RuntimeError("Yeniden deneme hakkı bitti")


def cok_parcali(alanlar: dict[str, str], dosyalar: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """multipart/form-data gövdesi kurar. dosyalar: ad -> (dosya_adı, içerik, mime)."""
    sinir = uuid.uuid4().hex
    parcalar = []
    for k, v in alanlar.items():
        parcalar.append(f"--{sinir}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    for k, (ad, icerik, mime) in dosyalar.items():
        parcalar.append(f"--{sinir}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{ad}\"\r\n"
                        f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + icerik + b"\r\n")
    parcalar.append(f"--{sinir}--\r\n".encode())
    return b"".join(parcalar), f"multipart/form-data; boundary={sinir}"


def _json(yol: str, **kw) -> dict:
    govde, _ = istek(yol, **kw)
    return json.loads(govde)


def durum() -> None:
    """Şartlar, kota ve ses modellerinin durumunu yazdırır."""
    s = _json("/terms/status")
    print(f"Kullanım şartları: sürüm {s.get('current_version')}, kabul edildi: {s.get('accepted')}")
    try:
        print("Kota:", json.dumps(_json("/quota"), ensure_ascii=False))
    except EvrenHatasi as e:
        print("Kota okunamadı:", e)
    for m in _json("/models").get("data", []):
        if m["id"] in ("voxcpm2", "qwen3-asr-1.7b"):
            print(f"Model {m['id']}: ücretsiz bitiş {m.get('pricing', {}).get('free_until')}")


def sartlar() -> None:
    """Şart metnini gösterir; yalnızca kullanıcı 'e' yazarsa kabul eder."""
    s = _json("/terms/status")
    if s.get("accepted"):
        print(f"Şartlar (sürüm {s['current_version']}) zaten kabul edilmiş.")
        return
    print(_json("/terms/text").get("content", ""))
    print("\n" + "=" * 60)
    cevap = input(f"Yukarıdaki EVREN kullanım şartlarını (sürüm {s['current_version']}) kabul ediyor musunuz? [e/h]: ")
    if cevap.strip().lower() != "e":
        print("Kabul edilmedi, hiçbir şey gönderilmedi.")
        return
    print("Kabul edildi:", _json("/terms/accept", json_govde={"version": s["current_version"]}))


if __name__ == "__main__":
    komut = sys.argv[1] if len(sys.argv) > 1 else "durum"
    {"durum": durum, "sartlar": sartlar}.get(komut, durum)()
