"use client";
import { FileUp } from "lucide-react";
import { useId, useState } from "react";
import { missingColumns, summariseCsv, type CsvSummary } from "@/lib/csv";

const MAX_BYTES = 5 * 1024 * 1024;

type Picked = { name: string; summary: CsvSummary };

/**
 * A real file input, shown as a button, that also takes a dropped file. The file is read in the browser and nothing leaves until the person presses Import.
 * `required` lists the column names the file must have; a file without them is refused here with the names, and `onText` gets an empty string.
 */
export function CsvFileInput({ onText, required = [], noun = "line" }: { onText: (text: string) => void; required?: string[]; noun?: string }) {
  const id = useId();
  const [picked, setPicked] = useState<Picked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  async function read(file: File | undefined) {
    if (!file) return;
    setError(null);
    const refuse = (msg: string) => { setPicked(null); setError(msg); onText(""); };
    if (file.size > MAX_BYTES) return refuse("That file is over 5 MB. Split it into smaller files.");
    try {
      const text = await file.text();
      const summary = summariseCsv(text);
      if (summary.rows === 0) return refuse(`That file has no data rows. It needs a header row and at least one ${noun}.`);
      const missing = missingColumns(summary.columns, required);
      if (missing.length) return refuse(`The file needs ${required.length > 1 ? "these columns" : "this column"}: ${required.join(", ")}. It has no ${missing.join(" or ")} column. Found: ${summary.columns.join(", ") || "none"}.`);
      setPicked({ name: file.name, summary });
      onText(text);
    } catch {
      refuse("Could not read that file. Save it as CSV and try again.");
    }
  }

  const s = picked?.summary;
  return (
    <div className="sx-field ll-file" data-dropzone data-over={over || undefined}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); void read(e.dataTransfer.files?.[0]); }}>
      <span className="sx-label">CSV file</span>
      <div className="ll-file__row">
        <input id={id} type="file" accept=".csv,text/csv,text/plain" className="ll-file__input" onChange={(e) => { void read(e.target.files?.[0]); e.target.value = ""; }} />
        <label htmlFor={id} className="sx-btn ll-file__btn"><FileUp size={14} aria-hidden />Choose a CSV file</label>
        <span className="ll-file__name">{picked ? picked.name : "No file chosen. You can also drop one here."}</span>
      </div>
      <div role="status" aria-live="polite">
        {error ? <span className="sx-field__error" role="alert">{error}</span> : null}
        {s ? (
          <>
            <p className="ll-file__sum">{s.rows} {s.rows === 1 ? "row" : "rows"}, {s.columns.length} columns. The first rows are below. Nothing is saved until you press Import.</p>
            <div className="ll-file__scroll" tabIndex={0} aria-label="Preview of the first rows">
              <table className="ll-file__table">
                <caption className="ll-file__cap">First {s.preview.length} of {s.rows}</caption>
                <thead><tr>{s.columns.map((c, i) => <th key={i} scope="col">{c}</th>)}</tr></thead>
                <tbody>{s.preview.map((r, i) => <tr key={i}>{s.columns.map((_, j) => <td key={j}>{r[j] ?? ""}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
