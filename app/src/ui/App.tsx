import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import { exportBackup, importIncoming, importZip, restoreFromFile, schemaVersion, startRuntime, type Runtime } from '../app/runtime';
import { listInstalledPacks, type ImportOutcome, type InstalledPack } from '../packs/importer';
import { Shell, type UpdateStatus } from '../platform/shell';

type Boot = { state: 'booting' } | { state: 'error'; message: string } | { state: 'ready'; rt: Runtime };

type Notice = { kind: 'ok' | 'info' | 'error'; text: string; details?: string[] };

const UPDATE_TEXT: Record<UpdateStatus, string> = {
  'up-to-date': 'التطبيق محدَّث ✅',
  'update-available': 'يوجد تحديث جديد',
  'needs-apk': 'هذا التحديث يحتاج تثبيت نسخة كاملة من التطبيق',
  offline: 'لا يوجد اتصال بالإنترنت',
  error: 'تعذّر التحقق من التحديثات',
  unsupported: 'التحديث التلقائي يعمل في تطبيق أندرويد فقط',
};

function describeImport(res: ImportOutcome): Notice {
  switch (res.status) {
    case 'imported':
      return { kind: 'ok', text: `تم استيراد «${res.title}» (v${res.version}): ${res.added} ريل جديد`, details: res.warnings };
    case 'updated':
      return {
        kind: 'ok',
        text: `تم تحديث «${res.title}» إلى v${res.version}: جديد ${res.added} · مُحدَّث ${res.updated} · محذوف ${res.removed}`,
        details: res.warnings,
      };
    case 'already-installed':
      return { kind: 'info', text: `«${res.title}» v${res.version} مثبّتة مسبقاً` };
    case 'rejected': {
      const why =
        res.reason === 'invalid-zip' ? 'الملف ليس حزمة ZIP صالحة' : res.reason === 'older-version' ? 'هذه نسخة أقدم من المثبّتة' : 'الحزمة فيها أخطاء ولم تُستورد';
      return { kind: 'error', text: why, details: [...res.errors, ...res.warnings] };
    }
  }
}

function formatDate(ms: number): string {
  return new Date(ms).toLocaleDateString('ar', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function App() {
  const [boot, setBoot] = useState<Boot>({ state: 'booting' });

  useEffect(() => {
    startRuntime().then(
      (rt) => setBoot({ state: 'ready', rt }),
      (err: unknown) => setBoot({ state: 'error', message: err instanceof Error ? err.message : String(err) }),
    );
  }, []);

  if (boot.state === 'booting') {
    return (
      <main className="center">
        <div className="spinner" aria-label="جارٍ التحميل" />
      </main>
    );
  }
  if (boot.state === 'error') {
    return (
      <main className="page">
        <h1>InstaAnki</h1>
        <section className="card error">
          <h2>تعذّر تشغيل التطبيق</h2>
          <p className="ltr mono">{boot.message}</p>
        </section>
      </main>
    );
  }
  return <Home rt={boot.rt} />;
}

function Home({ rt }: { rt: Runtime }) {
  const [packs, setPacks] = useState<InstalledPack[]>([]);
  const [dbVersion, setDbVersion] = useState<number>(rt.boot.schemaVersion);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [updateText, setUpdateText] = useState<string | null>(null);
  const zipInput = useRef<HTMLInputElement>(null);
  const backupInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setPacks(await listInstalledPacks(rt.db));
    setDbVersion(await schemaVersion(rt));
  }, [rt]);

  const run = useCallback(
    async (task: () => Promise<Notice | null>) => {
      setBusy(true);
      try {
        const n = await task();
        if (n) setNotice(n);
      } catch (err) {
        setNotice({ kind: 'error', text: 'حدث خطأ', details: [err instanceof Error ? err.message : String(err)] });
      } finally {
        setBusy(false);
        await refresh();
      }
    },
    [refresh],
  );

  // Shared "Share -> InstaAnki" zips: process what is waiting, then listen for more.
  const processIncoming = useCallback(
    () =>
      run(async () => {
        const { files } = await Shell.takeIncomingFiles();
        let last: Notice | null = null;
        for (const f of files) last = describeImport(await importIncoming(rt, f));
        return last;
      }),
    [rt, run],
  );

  useEffect(() => {
    // The app started correctly: tell the shell to keep this bundle.
    void Shell.notifyAppReady();
    void refresh();
    void processIncoming();
    const sub = Shell.addListener('incomingFile', () => void processIncoming());
    return () => {
      void sub.then((h) => h.remove());
    };
  }, [refresh, processIncoming]);

  const onZip = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (file) void run(async () => describeImport(await importZip(rt, new Uint8Array(await file.arrayBuffer()), 'manual')));
  };

  const onBackupFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!window.confirm('ستُستبدل كل بياناتك الحالية بالنسخة الاحتياطية (تُحفظ نسخة من بياناتك الحالية أولاً). متابعة؟')) return;
    void run(async () => {
      await restoreFromFile(rt, await file.text());
      return { kind: 'ok', text: 'تمت الاستعادة ✅' };
    });
  };

  const checkUpdates = () =>
    void run(async () => {
      const res = await Shell.checkForUpdate({ interactive: true });
      setUpdateText(UPDATE_TEXT[res.status] + (res.latest ? ` (v${res.latest})` : '') + (res.message ? `: ${res.message}` : ''));
      return null;
    });

  const { shell, boot } = rt;
  return (
    <main className="page">
      <header>
        <h1>InstaAnki</h1>
        <p className="muted">المرحلة 0 · الأساس</p>
      </header>

      {boot.restoredAfterRollback && (
        <section className="card warn">
          التحديث v{shell.rolledBackFrom} لم يعمل، فرجع التطبيق للنسخة السابقة واستُعيدت بياناتك كما كانت قبله.
        </section>
      )}
      {!boot.restoredAfterRollback && shell.rolledBackFrom && (
        <section className="card warn">التحديث v{shell.rolledBackFrom} لم يعمل، فرجع التطبيق للنسخة السابقة.</section>
      )}

      {notice && (
        <section className={`card ${notice.kind}`} role="status">
          <p>{notice.text}</p>
          {notice.details && notice.details.length > 0 && (
            <details>
              <summary>التفاصيل ({notice.details.length})</summary>
              <ul className="ltr mono">
                {notice.details.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </details>
          )}
          <button className="link" onClick={() => setNotice(null)}>
            إغلاق
          </button>
        </section>
      )}

      <section className="card">
        <h2>الإصدار</h2>
        <dl>
          <dt>الواجهة</dt>
          <dd className="ltr">
            v{shell.bundleVersion} <span className="tag">{shell.bundleSource === 'downloaded' ? 'محدَّثة' : 'مدمجة'}</span>
          </dd>
          <dt>القشرة</dt>
          <dd className="ltr">{shell.shellVersion ? `shell ${shell.shellVersion}` : 'متصفح'}</dd>
          <dt>قاعدة البيانات</dt>
          <dd className="ltr">schema v{dbVersion}</dd>
        </dl>
        <button onClick={checkUpdates} disabled={busy}>
          تحقق من التحديثات
        </button>
        {updateText && <p className="muted">{updateText}</p>}
      </section>

      <section className="card">
        <h2>الحزم</h2>
        {packs.length === 0 ? (
          <p className="muted">لا توجد حزم بعد. استورد ملف ZIP، أو شارك الملف من أي تطبيق إلى InstaAnki.</p>
        ) : (
          <ul className="packs">
            {packs.map((p) => (
              <li key={p.id}>
                <strong>{p.title}</strong>
                <span className="muted">
                  v{p.version} · {p.reels} ريل · {formatDate(p.imported_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <input ref={zipInput} type="file" accept=".zip,application/zip" hidden onChange={onZip} />
        <button onClick={() => zipInput.current?.click()} disabled={busy}>
          استيراد حزمة (ZIP)
        </button>
      </section>

      <section className="card">
        <h2>النسخ الاحتياطي</h2>
        <p className="muted">بياناتك محفوظة على الجهاز فقط. صدّر نسخة واحفظها في Drive أو الملفات.</p>
        <div className="row">
          <button onClick={() => void run(async () => (await exportBackup(rt), null))} disabled={busy}>
            تصدير نسخة احتياطية
          </button>
          <input ref={backupInput} type="file" accept=".json,application/json" hidden onChange={onBackupFile} />
          <button className="secondary" onClick={() => backupInput.current?.click()} disabled={busy}>
            استعادة من ملف
          </button>
        </div>
      </section>

      {busy && <div className="busy" aria-hidden="true" />}
    </main>
  );
}
