"""Thin web search UI — Person B's "ask a question, get trustworthy answers".

Pure standard-library `http.server`; no framework. Serves one search page and
a `/api/search` JSON endpoint backed by the same hybrid_search used by the
CLI. Every result shows its citation. The optional answer toggle maps to the
same off-by-default LLM/extractive step.
"""

from __future__ import annotations

import html
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .pipeline import open_store
from .search import hybrid_search

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Minister's Office — Knowledge Search (PoC)</title>
<style>
 :root{--bg:#f6f7f9;--card:#fff;--fg:#111820;--muted:#5b6773;--line:#e3e7ec;--accent:#0b5cad;--chip:#eef2f7}
 @media(prefers-color-scheme:dark){:root{--bg:#0f1419;--card:#171d24;--fg:#e8edf2;--muted:#93a1ad;--line:#242c35;--accent:#5aa9ef;--chip:#1e262f}}
 *{box-sizing:border-box} body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,Noto Sans,Arial,sans-serif;background:var(--bg);color:var(--fg)}
 header{padding:22px 18px;border-bottom:1px solid var(--line);background:var(--card)}
 h1{margin:0;font-size:18px} .sub{color:var(--muted);font-size:13px;margin-top:3px}
 main{max-width:860px;margin:0 auto;padding:18px}
 form{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px}
 input[type=text]{flex:1;min-width:240px;padding:11px 13px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--fg);font-size:15px}
 button{padding:11px 16px;border:0;border-radius:9px;background:var(--accent);color:#fff;font-size:14px;cursor:pointer}
 .opts{display:flex;gap:14px;align-items:center;color:var(--muted);font-size:13px;margin-bottom:14px;flex-wrap:wrap}
 .answer{background:var(--chip);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
 .hit{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px;margin-bottom:12px}
 .hit h3{margin:0 0 4px;font-size:15.5px}
 .meta{color:var(--muted);font-size:12.5px;margin-bottom:6px;display:flex;gap:8px;flex-wrap:wrap}
 .chip{background:var(--chip);border-radius:20px;padding:1px 9px}
 .src{font-size:12.5px;color:var(--accent);margin-bottom:6px;word-break:break-word}
 .snip{font-size:14px}
 .why{color:var(--muted);font-size:12px;margin-top:6px}
 .examples a{color:var(--accent);text-decoration:none;margin-right:12px;font-size:13px;white-space:nowrap}
 .empty{color:var(--muted);padding:20px 0}
</style></head><body>
<header><h1>Minister's Office — Knowledge Search</h1>
<div class="sub">Retrieval-first PoC · local hybrid search (keyword + semantic) · multilingual · every result cited</div></header>
<main>
 <form id="f">
   <input type="text" id="q" name="q" placeholder="Ask a question, e.g. Letters to the President in 2025" autofocus>
   <button type="submit">Search</button>
 </form>
 <div class="opts">
   <label><input type="checkbox" id="answer"> compose a short answer (optional)</label>
   <span class="examples">
     <a href="#" data-q="Show me everything on Quantum">Quantum</a>
     <a href="#" data-q="What meetings on semiconductor manufacturing?">Semiconductor</a>
     <a href="#" data-q="Letters to the President in 2025">Letters to the President</a>
     <a href="#" data-q="War room announcements about water supply">Water supply</a>
   </span>
 </div>
 <div id="results"></div>
</main>
<script>
 const $=s=>document.querySelector(s);
 async function run(q){
   if(!q) return;
   $('#q').value=q;
   $('#results').innerHTML='<div class="empty">Searching…</div>';
   const r=await fetch('/api/search?'+new URLSearchParams({q,answer:$('#answer').checked?'1':'0'}));
   const d=await r.json();
   render(d);
 }
 function esc(s){const e=document.createElement('div');e.textContent=s||'';return e.innerHTML;}
 function render(d){
   let h='';
   if(d.answer){h+='<div class="answer"><b>Answer:</b> '+esc(d.answer)+'</div>';}
   if(!d.hits.length){h+='<div class="empty">No records matched.</div>';}
   for(const [i,x] of d.hits.entries()){
     h+='<div class="hit"><h3>'+(i+1)+'. '+esc(x.title)+'</h3>'+
        '<div class="meta"><span class="chip">'+esc(x.category)+'</span>'+
        '<span class="chip">'+esc(x.source_type)+'</span>'+
        '<span class="chip">'+esc(x.language)+'</span>'+
        (x.date?'<span class="chip">'+esc(x.date)+'</span>':'')+
        (x.department?'<span class="chip">'+esc(x.department)+'</span>':'')+'</div>'+
        '<div class="src">📎 '+esc(x.provenance)+'</div>'+
        '<div class="snip">'+esc(x.snippet)+'</div>'+
        '<div class="why">match: '+esc(x.why)+' · score '+x.score.toFixed(4)+'</div></div>';
   }
   $('#results').innerHTML=h;
 }
 $('#f').addEventListener('submit',e=>{e.preventDefault();run($('#q').value);});
 document.querySelectorAll('.examples a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();run(a.dataset.q);}));
</script>
</body></html>"""


def _make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(200, PAGE)
                return
            if parsed.path == "/api/search":
                qs = urllib.parse.parse_qs(parsed.query)
                query = (qs.get("q") or [""])[0]
                want_answer = (qs.get("answer") or ["0"])[0] == "1"
                self._send(200, self._search(query, want_answer),
                           "application/json; charset=utf-8")
                return
            self._send(404, "not found", "text/plain")

        def _search(self, query, want_answer):
            store = open_store(cfg)
            try:
                res = hybrid_search(store, query, limit=10, answer=want_answer)
            finally:
                store.close()
            return json.dumps({
                "query": res.query,
                "answer": res.answer,
                "hits": [
                    {
                        "title": h.record.title,
                        "provenance": h.record.provenance,
                        "category": h.record.category,
                        "source_type": h.record.source_type,
                        "language": h.record.language,
                        "date": h.record.date,
                        "department": h.record.department,
                        "score": h.score,
                        "why": h.why,
                        "snippet": h.snippet,
                    } for h in res.hits
                ],
            }, ensure_ascii=False)

    return Handler


def serve(cfg: Config) -> None:
    handler = _make_handler(cfg)
    httpd = ThreadingHTTPServer((cfg.host, cfg.port), handler)
    print(f"KM search UI on http://{cfg.host}:{cfg.port}  (Ctrl-C to stop)")
    print(f"  db={cfg.db_path}  answer_default={cfg.answer}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
