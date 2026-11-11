# EVREN ile Türkçe Seslendirme ve Altyazı

Metni **Türkçe sese** çeviren ve sesten **Remotion uyumlu altyazı** çıkaran iki küçük Python betiği.
Her iki iş de [EVREN](https://evren.ssyz.org.tr) platformunun OpenAI uyumlu API'si üzerinden,
**Türkiye'deki sunucularda** çalışan açık modellerle yapılır:

| İş | Model | Uç nokta |
|---|---|---|
| Metinden sese | `voxcpm2` (sesler: deniz, ece, emre, kaan) | `POST /v1/audio/speech` |
| Sesten metne | `qwen3-asr-1.7b` | `POST /v1/audio/transcriptions` |

Kodla animasyon yaptığım [Remotion](https://www.remotion.dev) projesinde seslendirme ve altyazı adımlarını
yurt içi altyapıya taşımak için yazıldı. Çıktılar herhangi bir video aracında da kullanılabilir.

> Bu proje resmi değildir; EVREN ya da SSB ile bağlantısı yoktur.

## Gereksinimler

- Python 3.10+ (ek paket yok, yalnız standart kütüphane)
- `ffmpeg` ve `ffprobe` PATH üzerinde
- EVREN hesabı (e-Devlet ile giriş) ve **LLM Çıkarım** sınıfında bir API anahtarı

## Kurulum

1. EVREN panelinde **LLM Çıkarım → API Anahtarları → Yeni Anahtar**. Sınıf olarak **LLM Çıkarım** seçin
   ("Model Çıkarımı" sınıfı bu API'de 401 verir).
2. Anahtarı proje klasöründeki `.env` dosyasına yazın (bu dosya `.gitignore` içinde, depoya gitmez):
   ```
   EVREN_API_KEY=evren_llm_...
   ```
3. Kullanım şartlarını okuyup onaylayın (hesap başına bir kez). Betik metni gösterir, yalnız `e` yazarsanız onaylar:
   ```bash
   python evren_api.py sartlar
   python evren_api.py durum     # onay, günlük kota ve modellerin ücretsiz dönemini gösterir
   ```

## Kullanım

### 1. Seslendirme

Metin dosyasında her satır bir parçadır. `[sahne|sessizlik]` öneki isteğe bağlıdır ([örnek](ornek/metin.txt)):

```text
[giris|0.8] Merhaba! Bu ses, Evren platformundaki Türkçe ses modeliyle üretildi.
[nasil] Metni satır satır yazıyorsunuz.
```

```bash
python seslendir.py ornek/metin.txt --ses deniz --cikti cikti/ornek.mp3
```

Çıktılar:
- `cikti/ornek.mp3`: birleştirilmiş, ses seviyesi normalize edilmiş (-16 LUFS) seslendirme
- `cikti/ornek.parcalar.json`: her parçanın başlangıç/bitiş zamanı, Remotion'da sahne geçişleri için

```json
{ "i": 0, "sahne": "giris", "metin": "Merhaba! ...", "startMs": 500, "endMs": 7400 }
```

Hazır ses yerine İngilizce bir tarifle ses belirlemek için `--tarif "calm male narrator, documentary style"`.
Aynı metin ve ses tekrar istenirse API'ye yeniden gidilmez; önbellekten alınır.

### 2. Altyazı

```bash
python altyazi.py cikti/ornek.mp3
```

`cikti/ornek.captions.json` dosyası Remotion'ın `Caption` biçimindedir (`text, startMs, endMs, timestampMs, confidence`),
`@remotion/captions` ile doğrudan kullanılabilir.

- Yanında `*.parcalar.json` varsa her parça ayrı gönderilir ve altyazıya **senaryodaki metin** yazılır
  (özel adlar doğru kalır). ASR'nin duyduğu metin ekrana basılır; telaffuz kontrolü için kullanın.
  ASR metnini yazdırmak için `--asr-metni`.
- Zamanlama dosyası yoksa ses, sessizlik noktalarından en fazla 25 sn'lik parçalara bölünür (model penceresi ~30 sn).

**Sınır:** `qwen3-asr-1.7b` şu an kelime zamanı (`verbose_json`) döndürmüyor. Bu yüzden kelime zamanları
her parça içinde harf sayısına göre **yaklaşık** dağıtılır. Kelimeye kare kare senkron gereken animasyonlarda
yerel Whisper gibi kelime zamanı veren bir araç daha isabetlidir.

## Remotion'da kullanma

```tsx
import { Audio, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import parcalar from "../public/ornek.parcalar.json";

export const Ornek = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = (frame / fps) * 1000;
  const aktif = parcalar.find((p) => ms >= p.startMs && ms < p.endMs);
  return (
    <>
      <Audio src={staticFile("ornek.mp3")} />
      {aktif && <div style={{ fontSize: 48 }}>{aktif.sahne}</div>}
    </>
  );
};
```

## Deneyimler ve ipuçları

İlk denemelerde ASR çıktısıyla karşılaştırarak gördüklerim:

- **Kısaltmaları ve marka adlarını normal yazın.** `EVREN` büyük harfle yazılınca anlaşılmaz okundu (ASR "Evrienen" duydu),
  `Evren` yazınca doğru okundu. `voxcpm2` gibi model adları da anlaşılmaz okunuyor.
- **Rakamları yazıyla yazın.** `09.05` "sıfır dokuz sıfır beş" diye okundu; "saat dokuzu beş geçe" yazınca doğru çıktı.
- Remotion gibi yabancı adlar ASR'de farklı yazılabiliyor (ör. "Remoshin"); altyazıda senaryo metni kullanıldığı için sorun olmuyor.

## Kota ve ücret

- Günlük 15 milyon token; `python evren_api.py durum` kalan kotayı ve yenilenme zamanını gösterir.
- EVREN'e göre çıkarım istekleri **1 Aralık 2026'ya kadar ücretsiz**. Sonrası için platformu kontrol edin.
- 429 ve 503 yanıtlarında betik `Retry-After` kadar bekleyip yeniden dener.

## Lisans

[MIT](LICENSE)
