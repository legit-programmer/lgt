import "./StartupOverlay.css";

/** A local, abstract workspace scene shown while the backend and workspace boot. */
export function StartupOverlay() {
  return (
    <main className="startup-overlay" aria-busy="true">
      <div className="startup-silhouette" aria-hidden="true">
        <aside className="startup-silhouette-sidebar">
          <i className="startup-silhouette-brand" />
          <i className="startup-silhouette-line startup-silhouette-line--wide" />
          <i className="startup-silhouette-line" />
          <i className="startup-silhouette-line startup-silhouette-line--short" />
          <i className="startup-silhouette-divider" />
          <i className="startup-silhouette-line startup-silhouette-line--wide" />
          <i className="startup-silhouette-line" />
          <i className="startup-silhouette-line startup-silhouette-line--short" />
        </aside>
        <section className="startup-silhouette-conversation">
          <i className="startup-silhouette-header" />
          <div className="startup-silhouette-message startup-silhouette-message--human">
            <i />
            <i />
          </div>
          <div className="startup-silhouette-message">
            <i />
            <i />
            <i />
          </div>
          <i className="startup-silhouette-composer" />
        </section>
        <aside className="startup-silhouette-detail">
          <i className="startup-silhouette-line startup-silhouette-line--wide" />
          <i className="startup-silhouette-card" />
          <i className="startup-silhouette-line" />
          <i className="startup-silhouette-line startup-silhouette-line--short" />
        </aside>
      </div>
      <div className="startup-frost" aria-hidden="true" />

      <section className="startup-card" role="status" aria-live="polite">
        <div className="startup-mark" aria-hidden="true">
          <svg viewBox="0 0 64 64" focusable="false">
            <path d="M24 16v26c0 3.3 2.7 6 6 6h14" />
          </svg>
        </div>
        <h1>Setting up your Lgt workspace</h1>
        <p className="startup-caption">Connecting to your local workspace…</p>
        <div className="startup-progress" aria-hidden="true"><i /></div>
      </section>
    </main>
  );
}
