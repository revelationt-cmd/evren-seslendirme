# EVREN ile Türkçe Seslendirme ve Altyazı

Metni **Türkçe sese** çeviren, sesten **Remotion uyumlu altyazı** çıkaran ve seslendirmeyi senaryoyla
karşılaştırıp **telaffuz hatalarını ölçen** küçük Python betikleri.
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
- İsteğe bağlı: [`turkce-normalize`](https://github.com/seslen-tr/turkce-normalize) (`--normalize` ve adil WER ölçümü için,
  o da bağımlılıksız): `pip install turkce-normalize`
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

**Metin normalizasyonu (`--normalize`).** Rakam, tarih, saat, yüzde, para ve kısaltmaları modele göndermeden önce
Türkçe okunuşa çevirir; metni elle düzeltmek gerekmez ([örnek](ornek/ham_metin.txt)):

```bash
python seslendir.py ornek/ham_metin.txt --normalize --cikti cikti/ham.mp3
```

```text
Cumhuriyet 29.10.1923 tarihinde ilan edildi, toplantı saat 09:05'te başlıyor.
→ Cumhuriyet yirmi dokuz ekim bin dokuz yüz yirmi üç tarihinde ilan edildi, toplantı saat dokuz sıfır beşte başlıyor.
TBMM'de bugün %18 KDV ve 1.250,50 TL'lik bütçe konuşuldu.
→ te be me mede bugün yüzde on sekiz katma değer vergisi ve bin iki yüz elli lira elli kuruşluk bütçe konuşuldu.
```

Kendi özel adlarınız için `--telaffuz sozluk.json` (biçim: [ornek/telaffuz.json](ornek/telaffuz.json)); paketin gömülü
sözlüğüne eklenir. Modele giden metin `parcalar.json` içinde `okunan` alanına yazılır; altyazıda yine senaryo kullanılır.

**Hız (`--hiz`).** voxcpm2 OpenAI'daki `speed` alanını kabul ediyor; süre hızla orantılı değişiyor
(aynı cümle 1.0'da 4,8 sn, 0.96'da 5,0 sn, 0.8'de 6,0 sn). Tanıtım cümlelerinde `--hiz 0.96` (%4 yavaş) daha sakin bir ton verir.

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

### 3. Telaffuz kontrolü (WER)

Üretilen sesi ASR'den geçirip senaryoyla kelime kelime karşılaştırır. Hatalı okunan yeri dinlemeden bulmak için:

```bash
python karsilastir.py cikti/ornek.mp3 --ozel Evren,Remotion
```

```text
WER: %10.0  (6 hata / 60 kelime, 0 fazladan kelime)
  Sayılar     %  0.0  (0/16)
  Özel adlar  %  0.0  (0/3)
  Diğer       % 14.6  (6/41)

Hatalar (senaryo -> duyulan):
  [03] diger   senkronluyor -> senkronlıyor
```

- Sayılar ve özel adlar ayrı raporlanır; Türkçe seslendirmede hatanın çoğu bu iki grupta çıkıyor. Özel ad, senaryoda
  cümle başı dışında büyük harfle başlayan kelimedir; `--ozel` ile ek ad verilebilir.
- `turkce-normalize` kuruluysa iki taraf da okunuşa çevrilir. ASR sayıları rakamla yazdığı (`29 Ekim 1923`) için
  paket olmadan sayılar haksız yere hata sayılır.
- ASR sonucu `<ses>.asr.json` dosyasında saklanır, tekrar çalıştırınca API'ye gidilmez (`--yeniden` ile zorlanır).
  Ayrıntılı rapor `<ses>.wer.json` dosyasına yazılır.
- Sınır: harf harf okunan kısaltmaları ("te be me mede") ve yabancı adları ASR farklı yazabiliyor ("debememe de",
  "remoşun"). Bu satırlar her zaman okuma hatası değildir; kulakla kontrol edin.

## Videoya ekleme

Seslendirme klipten uzunsa video bitince ses kesilmesin, yumuşakça kapansın (`-shortest` + son 0,7 sn'de `afade`):

```bash
# klip 7.9 sn: kısılma 7.9 - 0.7 = 7.2 sn'de başlar
ffmpeg -i klip.mp4 -i cikti/ornek.mp3 -map 0:v -map 1:a -c:v copy \
  -af "afade=t=out:st=7.2:d=0.7" -c:a aac -b:a 128k -shortest cikis.mp4
```

- Konuşma için AAC 96-128k yeterli, dosya boyutu belirgin küçülür.
- Tarayıcılar otomatik oynatmaya yalnız sessiz videoda izin verir. Sayfaya gömülen videoyu `autoplay muted playsinline`
  ile başlatıp üzerine "sesi aç" düğmesi koymak hem bu kurala uyar hem izleyiciye seçim bırakır.

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

Normalizasyonu aynı ham metinle ([ornek/ham_metin.txt](ornek/ham_metin.txt), 4 parça, 60 kelime) ölçtüğümde:

| | WER | Sayı hatası | Duyulan örnek |
|---|---|---|---|
| Ham metin | %18,3 | %18,8 (3/16) | "29.10.1923" → "29 Eylül 1922", "1.250,50 TL" → "bin bin ondu iki bin elli" |
| `--normalize --hiz 0.96` | %10,0 | %0 (0/16) | Tarih, saat, yüzde ve tutar doğru duyuldu |

Kalan hataların çoğu ASR'nin harf harf okunan kısaltmayı birleştirmesinden geliyor ("te be me mede" → "debememe de").

## Teşekkürler

Bu sürümdeki eklemeler EVREN forumundaki [rehber konusuna](https://evren.ssyz.org.tr/forum/t/01a1ca36-2d24-74b1-9ac0-019a0b5e1a55)
gelen katkılardan çıktı:

- **Mehmet Veysel D.**: [turkce-normalize](https://github.com/seslen-tr/turkce-normalize) paketi ve telaffuz sözlüğü
  fikri (`--normalize`, `--telaffuz`).
- **Mustafa Ş.**: %4 yavaşlatma (`--hiz`), videoya eklerken `-shortest` + `afade` ve AAC 96-128k, tarayıcı otomatik
  oynatma notu, sayı ve özel ad hatalarını ayrı ölçme önerisi (`karsilastir.py`).

## Kota ve ücret

- Günlük 15 milyon token; `python evren_api.py durum` kalan kotayı ve yenilenme zamanını gösterir.
- EVREN'e göre çıkarım istekleri **1 Aralık 2026'ya kadar ücretsiz**. Sonrası için platformu kontrol edin.
- 429 ve 503 yanıtlarında betik `Retry-After` kadar bekleyip yeniden dener.

## Lisans

[MIT](LICENSE)
