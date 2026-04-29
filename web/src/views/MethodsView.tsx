import { Fragment, useState } from "react";
import type { AppData, BertopicTopic } from "../lib/data";
import { THREAD_COLORS } from "../lib/threads";

interface Props {
  data: AppData;
}

export function MethodsView({ data }: Props) {
  return (
    <div className="methods-view">
      <header className="methods-hero">
        <h2>Methods &amp; validity</h2>
        <p className="muted">
          Construct validity (BERTopic vs LLM threads), inferential statistics
          (bootstrap CI + permutation tests), and parameter sensitivity for the
          discourse-lens pipeline. Findings here either support or qualify the
          headline claims in <a href="#/discourse">discourse</a> and{" "}
          <a href="#/timeline">timeline</a>.
        </p>
      </header>

      <AboutSection />
      <BiasInferenceSection data={data} />
      <ConstructValiditySection data={data} />
      <SensitivitySection data={data} />
      <CaveatsSection data={data} />
      <ContactSection />
    </div>
  );
}

function ContactSection() {
  return (
    <section className="methods-section contact-section">
      <h3>Get in touch</h3>
      <p>
        I welcome <strong>inquiries</strong>, <strong>revision suggestions</strong>,
        and <strong>collaboration ideas</strong> — especially from researchers
        who would code the threads differently than I did, or who know of
        prior cross-field bibliometric comparisons I should be citing. If a
        keyword that matters to your work is missing or mislabeled, please
        flag it.
      </p>
      <div className="contact-grid">
        <a className="contact-pill primary" href="mailto:jmoon19@ua.edu?subject=discourse-lens%20feedback">
          <span className="label">Email</span>
          <span className="value">jmoon19@ua.edu</span>
        </a>
        <a className="contact-pill" href="https://github.com/Educatian/discourse-lens/issues/new"
           target="_blank" rel="noreferrer noopener">
          <span className="label">GitHub issue</span>
          <span className="value">file a revision suggestion</span>
        </a>
        <span className="contact-pill static">
          <span className="label">Affiliation</span>
          <span className="value">Dr. Jewoong Moon · University of Alabama · ADDIE Lab</span>
        </span>
      </div>
    </section>
  );
}

function AboutSection() {
  return (
    <section className="methods-section about-section">
      <h3>About this dashboard</h3>
      <div className="about-grid">
        <div>
          <p>
            Built by <strong>Dr. Jewoong Moon</strong>, Assistant Professor of
            Instructional Technology at the University of Alabama and director of
            the <em>ADDIE Lab</em>. Released as a teaching artifact for graduate
            students entering Learning Sciences or Educational Technology — a
            small, evidence-informed alternative to inherited folklore about
            "how the fields differ."
          </p>
          <p className="muted small">
            This is not a methods paper and not novel methodologically (KeyBERT,
            BERTopic, LLM coding are off-the-shelf). It borrows insights from
            Hoadley, Sawyer, Reigeluth, Dede and others — and tries to render the
            patterns those writings predict as something a curious newcomer can
            click through in a single seminar session.
          </p>
        </div>
        <div className="about-meta">
          <div className="meta-row">
            <span className="meta-label">Affiliation</span>
            <span>ADDIE Lab · University of Alabama</span>
          </div>
          <div className="meta-row">
            <span className="meta-label">Source</span>
            <a href="https://github.com/Educatian/discourse-lens"
               target="_blank" rel="noreferrer noopener">
              github.com/Educatian/discourse-lens
            </a>
          </div>
          <div className="meta-row">
            <span className="meta-label">Contact</span>
            <a href="mailto:jmoon19@ua.edu">jmoon19@ua.edu</a>
          </div>
          <div className="meta-row">
            <span className="meta-label">Suggested citation</span>
            <span className="cite">
              Moon, J. (2026). <em>discourse-lens: A side-by-side discourse map
              of Learning Sciences and Educational Technology journal abstracts</em>
              [Web dashboard]. https://educatian.github.io/discourse-lens/
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function BiasInferenceSection({ data }: { data: AppData }) {
  const tt = data.threadTimeline;
  if (!tt?.bias) {
    return (
      <section className="methods-section">
        <h3>Inferential statistics</h3>
        <div className="empty">Run <code>dlens export</code> to compute bootstrap CIs + permutation tests.</div>
      </section>
    );
  }
  const rows = Object.entries(tt.bias)
    .map(([id, b]) => ({ id, ...b, name: tt.threads.find((t) => t.id === id)?.display_name ?? id }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

  return (
    <section className="methods-section">
      <h3>1. Inferential statistics — thread bias deltas</h3>
      <p className="muted small">
        Δ = ET share − LS share (papers tagged with thread, divided by field
        size). 95% percentile bootstrap CI from B={tt.stats?.n_boot ?? 1000}.
        Two-sided permutation test against the null of identical thread
        prevalence (B={tt.stats?.n_perm ?? 2000} relabelings of field).
      </p>
      <table className="bias-table">
        <thead>
          <tr>
            <th>Thread</th>
            <th>n LS</th>
            <th>n ET</th>
            <th>Δ (pp)</th>
            <th>95% CI</th>
            <th>p (perm)</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sig = r.p_perm < 0.001 ? "***" : r.p_perm < 0.01 ? "**" : r.p_perm < 0.05 ? "*" : "ns";
            const cls = sig === "ns"
              ? "neutral"
              : r.delta > 0 ? "et" : "ls";
            return (
              <tr key={r.id}>
                <td>
                  <span className="swatch" style={{ background: THREAD_COLORS[r.id] ?? "#888" }} />
                  {r.name}
                </td>
                <td className="num">{r.n_ls}</td>
                <td className="num">{r.n_et}</td>
                <td className={`num strong ${cls}`}>
                  {r.delta > 0 ? "+" : ""}{(r.delta * 100).toFixed(1)}
                </td>
                <td className="num">[{(r.delta_lo * 100).toFixed(1)}, {(r.delta_hi * 100).toFixed(1)}]</td>
                <td className="num">{r.p_perm < 0.001 ? "<.001" : r.p_perm.toFixed(3)}</td>
                <td><span className={`sig sig-${sig}`}>{sig}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function ConstructValiditySection({ data }: { data: AppData }) {
  const cf = data.confusion;
  const topics = data.topics;
  const [openTopicId, setOpenTopicId] = useState<number | null>(null);

  if (!cf || !topics) {
    return (
      <section className="methods-section">
        <h3>2. Construct validity — BERTopic vs LLM threads</h3>
        <div className="empty">Run <code>dlens bertopic</code> to generate topics.json + topic_thread_confusion.json.</div>
      </section>
    );
  }

  // Normalize confusion by topic (row): P(thread | topic). Reordering rows by
  // dominant thread makes the diagonal pattern easy to read.
  const rowSums = cf.confusion.map((r) => Math.max(r.reduce((a, b) => a + b, 0), 1));
  const dominantThread = cf.confusion.map((r) => r.indexOf(Math.max(...r)));
  const order = cf.topic_ids.map((_, i) => i).sort((a, b) => {
    const da = dominantThread[a];
    const db = dominantThread[b];
    if (da !== db) return da - db;
    return rowSums[b] - rowSums[a];
  });
  const maxCellShare = Math.max(
    ...cf.confusion.flat().map((c, idx) => c / rowSums[Math.floor(idx / cf.thread_ids.length)])
  );

  const topicById = new Map<number, BertopicTopic>();
  for (const t of topics.topics) topicById.set(t.id, t);

  return (
    <section className="methods-section">
      <h3>2. Construct validity — BERTopic vs LLM threads</h3>
      <p className="muted small">
        {cf.method} · {topics.n_topics} topics, {topics.n_outliers} outliers ·
        {" "}<strong>diagonal alignment {(cf.diagonal_score * 100).toFixed(1)}%</strong>{" "}
        ({cf.diagonal_score >= 0.6 ? "strong" : cf.diagonal_score >= 0.4 ? "moderate" : "weak"} match).
        Cell shade = P(thread | topic). Click a topic row to see top words and exemplar papers.
      </p>
      <div className="confusion-wrap">
        <table className="confusion-table">
          <thead>
            <tr>
              <th>Topic</th>
              <th>n</th>
              {cf.thread_display_names.map((nm, i) => (
                <th key={i} title={nm}>
                  <span className="swatch" style={{ background: THREAD_COLORS[cf.thread_ids[i]] ?? "#888" }} />
                  {nm.split(" ")[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {order.map((i) => {
              const tid = cf.topic_ids[i];
              const topic = topicById.get(tid);
              const isOpen = openTopicId === tid;
              const head = topic?.top_words.slice(0, 4).join(", ") ?? `Topic ${tid}`;
              return (
                <Fragment key={tid}>
                  <tr className={isOpen ? "open" : ""} onClick={() => setOpenTopicId(isOpen ? null : tid)}>
                    <td className="topic-head">
                      <span className="topic-id">#{tid}</span> {head}
                    </td>
                    <td className="num">{topic?.size ?? 0}</td>
                    {cf.confusion[i].map((c, j) => {
                      const share = c / rowSums[i];
                      const opacity = Math.min(share / Math.max(maxCellShare, 0.01), 1);
                      return (
                        <td key={j} className="cell"
                            style={{ background: opacity > 0.02
                                ? `rgba(31, 119, 180, ${opacity * 0.85})`
                                : undefined }}
                            title={`${c} papers · ${(share * 100).toFixed(0)}%`}>
                          {c > 0 ? c : ""}
                        </td>
                      );
                    })}
                  </tr>
                  {isOpen && topic && (
                    <tr className="topic-detail">
                      <td colSpan={2 + cf.thread_ids.length}>
                        <div className="topic-words">
                          <strong>Top words:</strong> {topic.top_words.join(", ")}
                          <span className="muted"> · {topic.ls_count} LS, {topic.et_count} ET</span>
                        </div>
                        <ul className="exemplars">
                          {topic.exemplars.map((ex) => (
                            <li key={ex.doi}>
                              <span className={`field-tag ${ex.field.toLowerCase()}`}>{ex.field}</span>
                              <span className="ex-year">{ex.year}</span>
                              <span className="ex-title">{ex.title}</span>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SensitivitySection({ data }: { data: AppData }) {
  const sens = data.sensitivity;
  if (!sens) {
    return (
      <section className="methods-section">
        <h3>3. Parameter sensitivity</h3>
        <div className="empty">Run <code>dlens sensitivity</code> to generate sensitivity.json.</div>
      </section>
    );
  }
  return (
    <section className="methods-section">
      <h3>3. Parameter sensitivity</h3>
      <p className="muted small">
        Top-K Jaccard near 1.0 = top keywords stable across the parameter range
        (results are not threshold-artifacts). Reference settings highlighted.
      </p>
      <div className="sensitivity-grid">
        <SweepTable
          title={`Cosine merge threshold (top-${sens.cosine_merge_sweep.top_k} keyword Jaccard)`}
          rows={sens.cosine_merge_sweep.fields}
          keyName="cosine"
          extraName="n_canonicals"
          extraLabel="canonicals"
          jaccardField="top_k_jaccard"
          refValue={sens.cosine_merge_sweep.ref}
        />
        <SweepTable
          title={`NPMI edge threshold (top-${sens.npmi_sweep.n_focus_nodes} node neighbor-set Jaccard)`}
          rows={sens.npmi_sweep.fields}
          keyName="npmi"
          extraName="n_links"
          extraLabel="links"
          jaccardField="neighbor_jaccard"
          refValue={sens.npmi_sweep.ref}
        />
      </div>
    </section>
  );
}

interface SweepTableProps {
  title: string;
  rows: { ls: any[]; et: any[] };
  keyName: "cosine" | "npmi";
  extraName: "n_canonicals" | "n_links";
  extraLabel: string;
  jaccardField: "top_k_jaccard" | "neighbor_jaccard";
  refValue: number;   // reference parameter value to highlight; renamed from "ref" because React reserves ref
}

function SweepTable({ title, rows, keyName, extraName, extraLabel, jaccardField, refValue }: SweepTableProps) {
  const fields = ["ls", "et"] as const;
  const sweepValues = rows.ls.map((r: any) => r[keyName]);
  return (
    <div className="sweep-card">
      <h4>{title}</h4>
      <table className="sweep-table">
        <thead>
          <tr>
            <th></th>
            {sweepValues.map((v: number) => (
              <th key={v} className={Math.abs(v - refValue) < 1e-9 ? "ref" : ""}>{v.toFixed(2)}{Math.abs(v - refValue) < 1e-9 ? "*" : ""}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <Fragment key={f}>
              <tr>
                <td className="row-label">{f.toUpperCase()} Jaccard</td>
                {rows[f].map((r: any, i: number) => {
                  const v = r[jaccardField];
                  const isRef = Math.abs(r[keyName] - refValue) < 1e-9;
                  const cls = v >= 0.85 ? "good" : v >= 0.7 ? "ok" : "weak";
                  return (
                    <td key={i} className={`num ${cls} ${isRef ? "ref" : ""}`}>
                      {v.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
              <tr>
                <td className="row-label small">{f.toUpperCase()} {extraLabel}</td>
                {rows[f].map((r: any, i: number) => (
                  <td key={i} className="num small muted">{r[extraName]}</td>
                ))}
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CaveatsSection({ data }: { data: AppData }) {
  const tt = data.threadTimeline;
  return (
    <section className="methods-section">
      <h3>4. Open limitations</h3>
      <ul className="caveats">
        <li>
          <strong>Single LLM coder.</strong> Threads tagged by{" "}
          {tt?.model ?? "the LLM"} via OpenRouter. <em>No human gold sample
          yet</em>; inter-rater reliability (Cohen's κ) not computed. The
          inferential CIs above describe sampling variability, not coding
          variability.
        </li>
        <li>
          <strong>Top-down taxonomy.</strong> 8 threads were defined a priori;
          the BERTopic confusion above is the construct-validity check (data
          can also self-organize). The id_systems thread was added after a
          first pass — that change should be flagged in any methods section
          as a post-hoc refinement, not a clean priori choice.
        </li>
        <li>
          <strong>Untagged 235.</strong>{" "}
          {(tt?.stats?.n_records ?? 0) - (tt?.stats?.n_tagged ?? 0)} of{" "}
          {tt?.stats?.n_records ?? 0} papers received no thread; the LLM was
          instructed to be conservative. These have not been audited for what
          they are (editorials? lit reviews? out-of-scope?).
        </li>
        <li>
          <strong>Conference proceedings excluded.</strong> ICLS, AECT
          proceedings are central LS/ET venues but only journal articles are
          in the corpus; LS engagement may be undercounted.
        </li>
        <li>
          <strong>Coverage asymmetry.</strong> Springer-published journals
          push only ~50–65% of abstracts to OpenAlex; T&amp;F ~33–71%; Indiana
          Univ Press / Emerald near 100%. Per-journal share is biased toward
          high-coverage venues.
        </li>
      </ul>
    </section>
  );
}
