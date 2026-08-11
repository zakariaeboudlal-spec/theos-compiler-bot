# 🔧 Theos Compiler Bot

**© 2024 smartpepole — All Rights Reserved**

---

## 📖 ما هو هذا المشروع؟

بوت تيليقرام متخصص لكمبايل مشاريع Theos على iOS. المستخدم يرفع ملف مضغوط (zip/rar/7z) يحتوي مشروع Theos، والبوت يكمبايله ويرجع له ملف `.deb` أو `.dylib` أو `.framework` جاهز.

### ✨ المميزات
- دعم صيغ: zip, rar, 7z, tar.gz, tar.bz2
- حجم ملف حتى 100MB
- كمبايل متوازي (3 builds في نفس الوقت)
- إلغاء البيلد في أي لحظة
- تصحيح تلقائي لمسار THEOS في Makefile
- إرسال لوق كامل عند الفشل
- إعادة تشغيل تلقائية عبر systemd

---

## 🖥️ متطلبات السيرفر

- Ubuntu 20.04+ أو Debian 11+
- Python 3.10+
- Theos مثبت
- unrar, p7zip-full
- حساب بوت تيليقرام

---

## 🚀 تثبيت Theos من theos.dev

### الخطوة 1 — تثبيت المتطلبات

```bash
sudo apt-get update
sudo apt-get install -y git curl make clang
```

### الخطوة 2 — تثبيت Theos

```bash
# إنشاء مجلد Theos
export THEOS=/home/smartpepole/theos

# تحميل Theos من السيرفر الرسمي
bash -c "$(curl -fsSL https://raw.githubusercontent.com/theos/theos/master/bin/install-theos)"
```

> **ملاحظة:** الأمر يحمل Theos تلقائياً من `https://theos.dev` ويثبت كل المتطلبات (toolchains, sdks)

### الخطوة 3 — إضافة THEOS للـ PATH

```bash
echo 'export THEOS=/home/smartpepole/theos' >> ~/.bashrc
echo 'export PATH=$THEOS/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```

### الخطوة 4 — تحميل iOS SDKs

```bash
git clone --recursive https://github.com/theos/sdks.git /tmp/theos_sdks
cp -r /tmp/theos_sdks/*.sdk $THEOS/sdks/
```

---

## 🤖 تثبيت وتشغيل البوت

### الخطوة 1 — تحميل المشروع

```bash
git clone https://github.com/smartpepole/theos-compiler-bot.git /home/smartpepole/theos-bot
cd /home/smartpepole/theos-bot
```

### الخطوة 2 — إعداد التوكن

افتح `bot.py` وعدّل السطر:

```python
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN_HERE"
```

احصل على توكن من [@BotFather](https://t.me/BotFather) على تيليقرام.

كذلك عدّل `LOG_GROUP_ID` بـ ID المجموعة السرية التي تريد يلوق فيها البيلدات:

```python
LOG_GROUP_ID = -100XXXXXXXXXX  # ID المجموعة (رقم سالب)
```

### الخطوة 3 — تشغيل سكريبت التثبيت

```bash
chmod +x install.sh
sudo ./install.sh
```

السكريبت يفعل:
1. تثبيت `python3`, `pip3`, `unrar`, `p7zip-full`
2. تثبيت مكتبات Python من `requirements.txt`
3. نسخ ملف الـ service لـ systemd
4. تفعيل وتشغيل البوت

### الخطوة 4 — التحقق من التشغيل

```bash
# حالة البوت
sudo systemctl status theos-bot

# مشاهدة اللوقات
sudo journalctl -u theos-bot -f
```

---

## ⚙️ إعدادات البوت (bot.py)

| المتغير | القيمة الافتراضية | الشرح |
|---|---|---|
| `TELEGRAM_TOKEN` | — | توكن البوت من BotFather |
| `THEOS_PATH` | `/home/smartpepole/theos` | مسار Theos على السيرفر |
| `WORK_DIR` | `/tmp/theos_builds` | مجلد مؤقت للبيلد |
| `MAX_CONCURRENT_BUILDS` | `3` | عدد البيلدات المتزامنة |
| `BUILD_TIMEOUT` | `900` (15 دقيقة) | مهلة البيلد بالثواني |
| `RATE_LIMIT_MINUTES` | `1` | الانتظار بين كل بيلد للمستخدم |
| `MAX_FILE_SIZE_MB` | `100` | أقصى حجم للملف بالـ MB |
| `LOG_GROUP_ID` | — | ID المجموعة الخاصة للوقات |

---

## 📱 طريقة استخدام البوت على تيليقرام

1. افتح البوت على تيليقرام
2. اكتب `/start`
3. ارفع ملف مضغوط يحتوي مشروع Theos كامل
4. انتظر — البوت يكمبايل ويرجع النتيجة

**يجب أن يحتوي المشروع على:**
- `Makefile` في الـ root
- ملف `control`
- ملفات السورس (`.m`, `.mm`, `.xm`, `.c`, `.cpp`)

---

## 🔄 إدارة الـ Service

```bash
# إعادة تشغيل
sudo systemctl restart theos-bot

# إيقاف
sudo systemctl stop theos-bot

# تفعيل التشغيل التلقائي
sudo systemctl enable theos-bot

# مشاهدة اللوقات
sudo journalctl -u theos-bot -f
```

---

## 📁 هيكل المشروع

```
theos-bot/
├── bot.py              # البوت الرئيسي (مع retry logic)
├── bot66666666.py      # نسخة بديلة (أبسط)
├── requirements.txt    # مكتبات Python
├── install.sh          # سكريبت التثبيت
├── theos-bot.service   # ملف systemd service
└── README.md           # هذا الملف
```

---

## 🛠️ حل المشاكل الشائعة

**البوت ما يشتغل:**
```bash
sudo journalctl -u theos-bot -n 50
```

**خطأ في الكمبايل:**
- تأكد أن `THEOS_PATH` صح في `bot.py`
- تأكد أن Theos مثبت صح
- شوف اللوق الكامل اللي يرسله البوت

**مشكلة في الصلاحيات:**
```bash
sudo chown -R smartpepole:smartpepole /home/smartpepole/theos
sudo chown -R smartpepole:smartpepole /home/smartpepole/theos-bot
```

---

## 👤 المطور

**smartpepole** — [@smartpepole](https://t.me/smartpepole)

© 2024 smartpepole. All Rights Reserved.
