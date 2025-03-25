# CPU-Only Local GPT-Neo AI GUI

**"Fişini çekemediğin yapay zeka senin modelin değildir"**
*Yerel, bağımsız ve tam kontrol sağlayan bir AI deneyimi.*

---

## Özellikler
- 🔋 **Tamamen CPU Tabanlı**: GPU gerektirmez, düşük kaynak tüketimi
- 🔒 **Yerel Çalışma**: İnternet bağlantısı veya bulut servisi gerekmez
- 📂 **Çoklu Dosya Desteği**: PDF, DOCX, HTML ve Markdown desteği
- 🛡️ **Şifre Korumalı**: CLI üzerinden özel şifre belirleme

---

## Kurulum

### 🐍 Temel Bağımlılıklar (Conda/Yum/Pacman ile)
```bash
# Miniconda/Anaconda (Python 3.9)
conda install -y gxx_linux-64 gcc_linux-64 python=3.9

# RHEL/CentOS/Fedora
sudo yum install -y gcc-c++ python3-devel glibc

# Arch/Manjaro
sudo pacman -S gcc python-devel glibc
```

### 📦 Python Bağımlılıkları
```bash
pip install -r requirements.txt

# Conda ile Özel Kurulumlar
conda install -c pytorch pytorch torchvision cpuonly -y
conda install -c conda-forge cxx-compiler -y
```

### 🚀 Model Dosyaları
1. Hugging Face'ten [GPT-Neo 1.3B](https://huggingface.co/EleutherAI/gpt-neo-1.3B) modelini indirin
2. Gerekli dosyaları `models/gpt-neo-1.3B/` klasörüne yerleştirin:
   - `model.safetensors`
   - `config.json`
   - `vocab.json`
   - `merges.txt`

### ⚙️ Yapılandırma
`neo_NiceGUI.py` dosyasında model yolunu güncelleyin:
```python
self.local_model_path = "/path/to/your/model/files"  # Model klasörünüzün yolu
```
---

## Kullanım
```bash
# Varsayılan Port (1919)
python neo_NiceGUI.py --password "özel_şifreniz"

# Özel Port ile
python neo_NiceGUI.py -p 1920 -pw "gizli_kod"
```

### 🌐 Tarayıcı Erişimi
`http://localhost:PORT` adresinden erişim sağlayın.

---

## 🛠️ Sistem Gereksinimleri
| Bileşen    | Minimum      | Önerilen     |
|------------|--------------|--------------|
| RAM        | 8 GB         | 16 GB+       |
| Depolama   | 10 GB        | 20 GB+       |
| İşletim Sistemi | Linux 5.4+   | Linux 6.1+   |

---

## 🧩 Bağımlılık Matrisi
| Paket          | Kurulum Yolu      | Versiyon     |
|----------------|-------------------|-------------|
| PyTorch        | `conda`           | >=2.0.0     |
| GCC            | Sistem Paketi     | >=9.4.0     |
| libstdc++      | Sistem Paketi     | >=11.2.0    |

---

## Lisans
Bu proje [AGPL-3.0 Lisansı](LICENSE) ile korunmaktadır. Ticari kullanımlar için izin gereklidir.

---

> **⚠️ Uyarı**: Yapay zeka modellerinin etik kullanımından tamamen siz sorumlusunuz.
> **🔌 Sloganımız**: *"Fişini çekemediğin yapay zeka senin modelin değildir"*

### Güncellenmiş Proje Yapısı

Proje dizininiz aşağıdaki gibi olmalıdır:

```
cpu-only-local-gptneo-ai-gui-main/
│
├── neo_NiceGUI.py
├── requirements.txt
├── README.md
└── models/
	└── gpt-neo-1.3B/ (veya indirdiğiniz model)
		├── model.safetensors
		├── config.json
		├── vocab.json
		└── merges.txt
```

## 🎁 Destek Ol
**Çalışmalarımın sürmesine olanak sağlamak için bağışta bulunabilirsiniz.**
*Lütfen bağış yapmadan önce en az iki kere düşünün çünkü geri ödemeler için ayıracak hiç zamanım ve imkanım yok.*
**Katkılarınız için paylaştıklarımı kullanan herkes adına teşekkürlerimi kabul edin.**

[![Papara ile Destekle](https://img.shields.io/badge/Bağış%20Yap-%E2%9D%A4-blue)](https://ppr.ist/1T9dx8tUT)
[![Donate using Papara](https://img.shields.io/badge/Donate-%E2%9D%A4-blue)](https://ppr.ist/1T9dx8tUT)

[![Papara ile Desteklen](docs/1513592797QR.png)](https://ppr.ist/1T99dYF5X)
