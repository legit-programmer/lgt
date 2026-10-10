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

      <section className="startup-card fv-glass" role="status" aria-live="polite">
        <div className="startup-emblem" aria-hidden="true">
          <span className="startup-emblem-halo" />
          <span className="startup-emblem-orbit startup-emblem-orbit--outer">
            <i />
          </span>
          <span className="startup-emblem-orbit startup-emblem-orbit--inner">
            <i />
          </span>
          <svg className="startup-emblem-mark" viewBox="0 0 64 64" focusable="false">
            <path d="M22 14v30c0 4.4 3.6 8 8 8h20" />
          </svg>
        </div>
        <p className="startup-overline fv-label">LGT · LOCAL WORKSPACE</p>
        <h1>Setting up your Lgt workspace</h1>
        <p className="startup-caption">Connecting to your local workspace.</p>
        <div className="startup-pulse" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
      </section>
    </main>
  );
}
