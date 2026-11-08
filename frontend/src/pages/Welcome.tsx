type Props = { onTryDemo: () => void; loading: boolean; error: string | null };

export default function Welcome({ onTryDemo, loading, error }: Props) {
  return (
    <div className="welcome">
      <header className="welcome-top">
        <span className="wordmark">
          <span className="wordmark-mark" aria-hidden="true" />
          GetPaid
        </span>
      </header>

      <section className="welcome-hero">
        <div className="welcome-copy">
          <h1>Your contract already says when you get paid. GetPaid makes sure you do.</h1>
          <p className="welcome-lede">
            Paste a freelance contract. GetPaid finds every payment in it, checks that the numbers add up,
            sends the invoices through PayPal, and shows you who has paid.
          </p>
          <div className="welcome-actions">
            <button className="button button-primary button-large" onClick={onTryDemo} disabled={loading}>
              {loading ? "Opening the demo…" : "Try the demo"}
            </button>
            <p className="fine-print">No sign-up. Runs on PayPal's sandbox, so no real money moves.</p>
          </div>
          {error && <p className="error-text" role="alert">{error}</p>}
        </div>

        <figure className="welcome-figure" aria-label="A contract line becoming a PayPal invoice">
          <div className="paper paper-small">
            <p className="paper-line">3. Payment Schedule</p>
            <p className="paper-line">(a) Brand discovery workshop and moodboard: $600, due on November 20, 2026.</p>
            <p className="paper-line">
              <mark className="swipe">(b) Primary logo design with two rounds of revisions: $1,200, due on December 4, 2026.</mark>
            </p>
            <p className="paper-line">(c) Brand guidelines document: $1,000, due within 15 days of final delivery.</p>
          </div>
          <div className="mini-invoice">
            <span className="mini-invoice-label">PayPal invoice</span>
            <strong>$1,200.00</strong>
            <span>Primary logo design</span>
            <span>Due Dec 4, 2026</span>
            <span className="badge badge-paid">Paid</span>
          </div>
        </figure>
      </section>

      <ol className="welcome-steps">
        <li><strong>Reads the contract.</strong> Every amount and date links back to the sentence it came from.</li>
        <li><strong>Checks the math.</strong> Flags payments that don't add up or have no due date.</li>
        <li><strong>Sends PayPal invoices.</strong> One per payment, after you approve them.</li>
        <li><strong>Tracks payment.</strong> See what's paid, waiting, and overdue.</li>
      </ol>
    </div>
  );
}
