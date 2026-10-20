import { StrictMode, useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
type Asset = {
  id: string;
  filename: string;
  kind: string;
  status: string;
  size: number;
  imported_at: string;
  captured_at: string | null;
  thumbnail_url: string | null;
  original_url: string;
  error: string | null;
  width: number | null;
  height: number | null;
};
const labels: Record<string, string> = {
  pending: "รอคิว",
  queued: "รอประมวลผล",
  processing: "กำลังประมวลผล",
  ready: "พร้อมใช้งาน",
  failed: "ล้มเหลว",
};
async function request(path: string, options?: RequestInit) {
  const r = await fetch(path, options);
  if (!r.ok) throw new Error(`ดำเนินการไม่สำเร็จ (${r.status})`);
  return r.json();
}
function App() {
  const [assets, setAssets] = useState<Asset[]>([]),
    [selected, setSelected] = useState<Asset | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [report, setReport] = useState<string[]>([]),
    [filter, setFilter] = useState("all");
  useEffect(() => {
    let live = true;
    const refresh = async () => {
      try {
        const rows = await request("/api/assets");
        if (live) {
          setAssets(rows);
          setError("");
        }
      } catch (e) {
        if (live) setError(String(e));
      }
    };
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setReport([]);
    try {
      const data = new FormData();
      Array.from(files).forEach((file) => data.append("files", file));
      const r = await request("/api/imports", { method: "POST", body: data });
      setReport(
        r.items.map(
          (i: { filename: string; status: string; error?: string }) =>
            `${i.filename}: ${i.error || { accepted: "รับไฟล์แล้ว", duplicate: "ไฟล์ซ้ำ อ้างอิงต้นฉบับเดิม" }[i.status] || i.status}`,
        ),
      );
      setAssets(await request("/api/assets"));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (selected) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [selected]);
  const active = assets.find((a) => a.id === selected?.id) || selected;
  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">YOUR PERSONAL MEDIA LIBRARY</p>
          <h1>AI Media Organizer</h1>
          <p>เก็บความทรงจำให้เป็นระเบียบ เริ่มจากคลังสื่อของคุณ</p>
        </div>
        <span className="phase">ช่วง A · คลังไฟล์</span>
      </header>
      <section className="import">
        <div>
          <h2>เพิ่มรูปภาพและวิดีโอ</h2>
          <p>
            JPEG, PNG, WebP, MP4 และ MOV · สูงสุด 250 MiB ต่อไฟล์ · ครั้งละ 50
            ไฟล์
          </p>
          <p className="muted">
            เก็บต้นฉบับไว้เสมอ ตรวจไฟล์ซ้ำอัตโนมัติ · AI
            และการค้นหาจะเพิ่มในช่วงถัดไป
          </p>
        </div>
        <label className="button">
          {busy ? "กำลังอัปโหลด…" : "＋ เลือกไฟล์"}
          <input
            aria-label="เลือกไฟล์นำเข้า"
            type="file"
            multiple
            accept=".jpg,.jpeg,.png,.webp,.mp4,.mov"
            disabled={busy}
            onChange={(e) => {
              void upload(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </section>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {report.length > 0 && (
        <section aria-live="polite" className="report">
          <h2>ผลการนำเข้า</h2>
          <ul>
            {report.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </section>
      )}
      <section className="stats">
        {[
          ["ทั้งหมด", assets.length],
          ["พร้อมใช้งาน", assets.filter((a) => a.status === "ready").length],
          [
            "อยู่ในคิว",
            assets.filter((a) =>
              ["pending", "queued", "processing"].includes(a.status),
            ).length,
          ],
          ["ล้มเหลว", assets.filter((a) => a.status === "failed").length],
        ].map(([name, count]) => (
          <div key={name}>
            <strong>{count}</strong>
            <span>{name}</span>
          </div>
        ))}
      </section>
      <div className="toolbar">
        <h2>คลังสื่อ</h2>
        <label>
          แสดง{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">ทั้งหมด</option>
            <option value="image">รูปภาพ</option>
            <option value="video">วิดีโอ</option>
            <option value="failed">งานล้มเหลว</option>
          </select>
        </label>
      </div>
      <section className="grid">
        {assets
          .filter(
            (a) => filter === "all" || a.kind === filter || a.status === filter,
          )
          .map((a) => (
            <button className="card" key={a.id} onClick={() => setSelected(a)}>
              {a.thumbnail_url ? (
                <img loading="lazy" src={a.thumbnail_url} alt={a.filename} />
              ) : (
                <div className="placeholder">
                  {a.kind === "video" ? "▷" : "▧"}
                </div>
              )}
              <div className="cardbody">
                <span className={`status ${a.status}`}>{labels[a.status]}</span>
                <h3>{a.filename}</h3>
                <p>
                  {(a.size / 1024 / 1024).toFixed(2)} MiB ·{" "}
                  {a.kind === "video" ? "วิดีโอ" : "รูปภาพ"}
                </p>
              </div>
            </button>
          ))}
      </section>
      {!assets.length && (
        <section className="empty">
          <h2>คลังสื่อของคุณเริ่มที่นี่</h2>
          <p>เลือกไฟล์ชุดแรกเพื่อนำเข้าและสร้างภาพตัวอย่าง</p>
        </section>
      )}
      {active && (
        <dialog
          ref={dialogRef}
          aria-label="รายละเอียดไฟล์"
          className="detail"
          onCancel={() => setSelected(null)}
        >
          <button autoFocus className="close" onClick={() => setSelected(null)}>
            ปิด
          </button>
          <h2>{active.filename}</h2>
          {active.kind === "video" ? (
            <video controls src={active.original_url} />
          ) : (
            active.thumbnail_url && (
              <img src={active.thumbnail_url} alt={active.filename} />
            )
          )}
          <p>สถานะ: {labels[active.status]}</p>
          <p>วันที่ถ่าย: {active.captured_at || "ไม่ทราบ"}</p>
          <p>นำเข้า: {new Date(active.imported_at).toLocaleString("th-TH")}</p>
          <p>
            ขนาดภาพ: {active.width || "—"} × {active.height || "—"}
          </p>
          {active.error && <p className="error">{active.error}</p>}
          <a href={active.original_url}>เปิดไฟล์ต้นฉบับ</a>
          {active.status === "failed" && (
            <button
              className="button"
              onClick={() => {
                void request(`/api/assets/${active.id}/retry`, {
                  method: "POST",
                })
                  .then((a) => {
                    setSelected(a);
                    setAssets((old) => old.map((x) => (x.id === a.id ? a : x)));
                  })
                  .catch((e) => setError(String(e)));
              }}
            >
              ลองประมวลผลใหม่
            </button>
          )}
        </dialog>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
