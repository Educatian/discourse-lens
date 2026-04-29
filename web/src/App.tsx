import { useEffect, useState } from "react";
import { DualNetworkView } from "./views/DualNetworkView";
import { TimelineView } from "./views/TimelineView";
import { DiscourseView } from "./views/DiscourseView";
import { CompareView } from "./views/CompareView";
import { MethodsView } from "./views/MethodsView";
import { FilterBar } from "./components/FilterBar";
import { loadAllData, type AppData } from "./lib/data";

type Route = "networks" | "timeline" | "discourse" | "compare" | "methods";

function parseRoute(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "timeline" || h === "discourse" || h === "compare" || h === "methods") return h;
  return "networks";
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute());
  const [data, setData] = useState<AppData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [regularize, setRegularize] = useState(false);
  const [activeThread, setActiveThread] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    loadAllData()
      .then(setData)
      .catch((e: Error) => setErr(e.message));
  }, []);

  return (
    <>
      <header className="topbar">
        <h1>discourse-lens</h1>
        <nav>
          <a href="#/networks" className={route === "networks" ? "active" : ""}>networks</a>
          <a href="#/timeline" className={route === "timeline" ? "active" : ""}>timeline</a>
          <a href="#/discourse" className={route === "discourse" ? "active" : ""}>discourse</a>
          <a href="#/compare" className={route === "compare" ? "active" : ""}>compare</a>
          <a href="#/methods" className={route === "methods" ? "active" : ""}>methods</a>
        </nav>
        <span className="sub">
          {data
            ? `${data.papers.length} papers · LS: ${data.networkLs.nodes.length} kw · ET: ${data.networkEt.nodes.length} kw`
            : err
              ? `data error: ${err}`
              : "loading…"}
        </span>
      </header>
      {data && (
        <FilterBar
          data={data}
          selected={selected}
          onSelect={setSelected}
          regularize={regularize}
          onRegularize={setRegularize}
        />
      )}
      <main>
        {!data && !err && <div className="empty">loading data…</div>}
        {err && <div className="empty">Could not load data files. Run <code>dlens export</code> from the pipeline.</div>}
        {data && route === "networks" && (
          <DualNetworkView
            data={data}
            selected={selected}
            onSelect={setSelected}
            regularize={regularize}
          />
        )}
        {data && route === "timeline" && (
          data.threadTimeline
            ? <TimelineView timeline={data.threadTimeline} />
            : <div className="empty">Timeline waiting for <code>dlens tag</code> to finish, then run <code>dlens export</code> and refresh.</div>
        )}
        {data && route === "discourse" && (
          <DiscourseView
            data={data}
            onPickThread={(id) => {
              setActiveThread(id);
              window.location.hash = "#/compare";
            }}
          />
        )}
        {data && route === "compare" && (
          <CompareView
            data={data}
            initialThread={activeThread}
            onSelectKeyword={(kw) => {
              setSelected(kw);
              window.location.hash = "#/networks";
            }}
          />
        )}
        {data && route === "methods" && <MethodsView data={data} />}
      </main>
    </>
  );
}
