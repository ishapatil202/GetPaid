import { useEffect, useState } from "react";
import { api } from "../api";
import { go } from "../router";
import { LATE_CLIENT_CONTRACT, SAMPLE_CONTRACT } from "../sampleContract";

const STEPS = ["Reading the contract", "Finding each payment", "Checking that the numbers add up"];

export default function NewContract() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const timer = window.setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 2500);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function readContract() {
    setLoading(true);
    setError(null);
    try {
      const contract = await api.createContract(text);
      go(`/contracts/${contract.id}`);
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  async function loadFile(file: File | undefined) {
    if (!file) return;
    setText(await file.text());
  }

  const tooShort = text.trim().length < 50;

  return (
    <div className="stack narrow">
      <a className="back-link" href="#/">All contracts</a>
      <h1>Add a contract</h1>
      <p className="muted">Paste the full text of a freelance contract or statement of work.</p>

      <div className="paper paper-input">
        <label htmlFor="contract-text" className="visually-hidden">Contract text</label>
        <textarea
          id="contract-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste your contract here…"
          disabled={loading}
          rows={18}
        />
      </div>

      <div className="row-actions">
        <button className="button" onClick={() => setText(SAMPLE_CONTRACT)} disabled={loading}>
          Sample: new project
        </button>
        <button className="button" onClick={() => setText(LATE_CLIENT_CONTRACT)} disabled={loading}>
          Sample: late client
        </button>
        <label className="button file-button">
          Open a .txt file
          <input type="file" accept=".txt,.md,text/plain" onChange={(e) => loadFile(e.target.files?.[0])} disabled={loading} />
        </label>
        <span className="spacer" />
        <button className="button button-primary" onClick={readContract} disabled={tooShort || loading}>
          {loading ? "Reading…" : "Read contract"}
        </button>
      </div>

      {loading && (
        <ol className="progress-steps" aria-live="polite">
          {STEPS.map((label, i) => (
            <li key={label} className={i < step ? "done" : i === step ? "current" : ""}>{label}</li>
          ))}
        </ol>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}
