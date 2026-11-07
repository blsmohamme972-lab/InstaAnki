# الإعداد والنشر

> هذا الدليل لمرة واحدة: إضافة المفاتيح، ثم تثبيت التطبيق أول مرة. بعدها كل التحديثات تصل تلقائياً.

## 1. المفاتيح (مرة واحدة، مهم جداً)

يحتاج الـ repo ثلاثة أسرار في **Settings ← Secrets and variables ← Actions ← New repository secret**:

| اسم السر | المحتوى | الاستخدام |
|---|---|---|
| `OTA_SIGNING_KEY` | ملف PEM كاملاً (يبدأ بـ `-----BEGIN PRIVATE KEY-----`) | توقيع تحديثات الواجهة |
| `ANDROID_KEYSTORE_BASE64` | محتوى `android-keystore-base64.txt` | توقيع ملف APK |
| `ANDROID_KEYSTORE_PASSWORD` | كلمة مرور الـ keystore | توقيع ملف APK |

- **المفتاح العام** المقابل لـ `OTA_SIGNING_KEY` موجود في `app/android/app/src/main/res/raw/ota_public_key.pem`. التطبيق يرفض أي تحديث غير موقّع بالمفتاح الخاص المطابق له.
- **احفظ نسخة** من المفتاحين (`ota-signing-key.pem` وملف `instaanki-release.p12` مع كلمة مروره) خارج GitHub أيضاً، في مدير كلمات مرور مثلاً:
  - إذا ضاع `OTA_SIGNING_KEY`، تحتاج مفتاحاً جديداً وAPK جديداً.
  - إذا ضاع الـ keystore، **لا يمكن تحديث التطبيق فوق النسخة المثبتة**. يلزم حذفه وإعادة تثبيته، فصدّر نسخة احتياطية قبل ذلك.
- **لا ترفع أي مفتاح خاص إلى الـ repo.** الملف `app/.gitignore` يمنع ملفات `.pem` و`.p12`.

### إنشاء مفاتيح جديدة (عند الحاجة)

```bash
# مفتاح توقيع التحديثات
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out ota-signing-key.pem
openssl pkey -in ota-signing-key.pem -pubout -out app/android/app/src/main/res/raw/ota_public_key.pem

# keystore الـ APK (alias يجب أن يكون instaanki)
keytool -genkeypair -keystore instaanki-release.p12 -storetype PKCS12 -alias instaanki \
  -keyalg RSA -keysize 4096 -validity 36500 -dname "CN=InstaAnki"
base64 -w0 instaanki-release.p12 > android-keystore-base64.txt
```

تغيير المفتاح العام يغيّر القشرة، أي يحتاج APK جديداً بـ `shellVersion` أعلى.

## 2. أول تثبيت

1. في GitHub افتح **Actions ← Release Android shell (APK) ← Run workflow**.
2. بعد انتهائه يظهر إصدار `shell-v1` في **Releases**، ومعه ملف `InstaAnki-shell-1.apk`.
3. افتح الصفحة من الجوال، حمّل الـ APK وثبّته. أندرويد سيطلب السماح بالتثبيت من المتصفح.

## 3. التحديثات بعد ذلك

### تحديث الواجهة (الأغلب، بدون APK)

1. عدّل الكود في `app/`.
2. ارفع `"version"` في `app/package.json`، مثلاً من `0.1.0` إلى `0.1.1`.
3. ادمج التعديل إلى `main`.
4. Action **Publish OTA update** تبني الواجهة وتوقّعها وتنشرها في إصدار `ota-channel`.
5. عند فتح التطبيق تظهر رسالة **"تحديث متاح"**، ويُحمَّل فقط ما تغيّر.

ملاحظات:
- **سطر الملاحظات** في رسالة التحديث هو أول سطر من رسالة الـ commit. يمكن كتابة ملاحظات مختلفة بتشغيل الـ Action يدوياً مع حقل `notes`.
- **بدون رفع `version`** لا يُنشر شيء، والـ Action تكتب تنبيهاً بذلك.
- **إذا لم تعمل النسخة الجديدة** (لم تبدأ خلال 15 ثانية)، يرجع التطبيق تلقائياً للنسخة السابقة ولا يعرضها مرة ثانية. وإذا كانت قد غيّرت قاعدة البيانات، تُستعاد البيانات من النسخة الاحتياطية التي أُخذت قبل التحديث.

### تحديث القشرة (نادراً، APK كامل)

عند تغيير كود أندرويد أو إضافة plugin أو صلاحية:

1. ارفع `def shellVersion = N` في `app/android/app/build.gradle`.
2. إذا كانت الواجهة الجديدة تحتاج هذه القشرة، ارفع `"minShellVersion"` في `app/package.json` إلى نفس الرقم.
3. شغّل **Release Android shell (APK)**.
4. التطبيقات القديمة ستعرض **"تحديث كبير متاح"** مع زر يفتح صفحة التنزيل.

## 4. التطوير محلياً

```bash
cd app
npm install
npm run dev          # في المتصفح: قاعدة بيانات في الذاكرة، بدون Android
npm test             # كل الاختبارات (تحتاج python3 + jsonschema لاختبار التطابق)
npm run typecheck
npm run sync         # بناء الواجهة ونسخها لمشروع Android
cd android && ./gradlew testDebugUnitTest assembleDebug
```

## 5. أين يوجد كل شيء

| المسار | المحتوى |
|---|---|
| `app/src/db/` | SQLite، الترحيلات، النسخ الاحتياطي |
| `app/src/packs/` | استيراد الحزم والتحقق منها وتنظيف SVG |
| `app/src/platform/shell.ts` | واجهة JS للقشرة الأصلية |
| `app/android/app/src/main/java/com/instaanki/app/` | القشرة: التحديث، التراجع، استقبال الملفات المشارَكة |
| `app/scripts/ota-publish.mjs` | بناء `latest.json` وتوقيعه |
| `.github/workflows/` | CI، نشر التحديثات، بناء الـ APK |
