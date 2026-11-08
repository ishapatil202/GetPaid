import { useEffect, useState } from "react";
import { api, ContractSummary } from "../api";
import { money, niceDate } from "../format";
import { go } from "../router";

export default function Contracts() {
  const [contracts, setContracts] = useState<ContractSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.contracts().then(setContracts).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Contracts</h1>
        <button className="button button-primary" onClick={() => go("/new")}>Add a contract</button>
      </div>

      {error && <p className="error-text" role="alert">{error}</p>}
      {contracts === null && !error && <p className="muted">Loading contracts…</p>}

      {contracts && contracts.length === 0 && (
        <div className="empty">
          <h2>No contracts yet</h2>
          <p>Add a freelance contract and GetPaid will find the payments in it.</p>
          <button className="button button-primary" onClick={() => go("/new")}>Add a contract</button>
        </div>
      )}

      {contracts && contracts.length > 0 && (
        <ul className="contract-list">
          {contracts.map((c) => (
            <li key={c.id}>
              <a className="contract-row" href={`#/contracts/${c.id}`}>
                <span className="contract-row-title">{c.client_name || c.title}</span>
                <span className="contract-row-total">{money(c.contract_total, c.currency)}</span>
                <span className="contract-row-progress">
                  {c.status === "sent" ? `${c.paid_count} of ${c.milestone_count} paid` : "Needs review"}
                </span>
                <span className="contract-row-date">Added {niceDate(c.created_at)}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
