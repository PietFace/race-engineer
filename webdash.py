"""Tweede scherm: een klein webservertje in het programma. Open het adres op je telefoon,
iPad of een andere pc in hetzelfde (wifi-)netwerk en je ziet een live dashboard."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # stuurt niets, kiest alleen de juiste netwerkkaart
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class WebDash:
    def __init__(self, provider, log, port=8770):
        """provider() -> dict met de live data"""
        self.provider = provider
        self.log = log
        self.port = port
        self.server = None
        self.viewers = {}          # ip -> laatste verzoek

    @property
    def url(self):
        return f"http://{local_ip()}:{self.port}"

    @property
    def running(self):
        return self.server is not None

    def viewer_count(self):
        now = time.time()
        return sum(1 for t in self.viewers.values() if now - t < 5)

    def start(self):
        if self.server:
            return True
        dash = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/api"):
                    dash.viewers[self.client_address[0]] = time.time()
                    try:
                        data = dash.provider()
                    except Exception as e:
                        data = {"fout": str(e)}
                    self._send(200, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                               "application/json; charset=utf-8")
                elif self.path in ("/", "/index.html"):
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._send(404, b"niet gevonden", "text/plain")

        try:
            self.server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError as e:
            self.log(f"Tweede scherm kon niet starten op poort {self.port}: {e}")
            self.server = None
            return False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.log(f"Tweede scherm actief: {self.url}")
        return True

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


PAGE = r"""<!doctype html>
<html lang="nl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0F1216">
<title>Race Engineer</title>
<style>
:root{--bg:#0F1216;--card:#171B21;--line:#262C35;--text:#E8EAED;--muted:#8A94A6;--acc:#FF8A00;--good:#3DDC84;--bad:#FF5A5F;--info:#5AB0FF}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--bg);color:var(--text);font-family:-apple-system,"Segoe UI",Inter,Roboto,sans-serif;height:100%}
body{padding:max(10px,env(safe-area-inset-top)) max(10px,env(safe-area-inset-right)) 10px max(10px,env(safe-area-inset-left));-webkit-user-select:none;user-select:none}
.top{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.dot{width:10px;height:10px;border-radius:50%;background:#555c66;flex:none}
.title{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sub{color:var(--muted);font-size:12px}
.fs{margin-left:auto;background:var(--card);border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:6px 10px;font-size:12px}
.flag{display:none;border-radius:10px;padding:8px;text-align:center;font-weight:800;letter-spacing:2px;margin-bottom:8px;font-size:15px}
.grid{display:grid;gap:8px;grid-template-columns:repeat(4,1fr)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;min-width:0}
.cap{color:var(--muted);font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase}
.big{font-size:clamp(28px,7vw,54px);font-weight:800;line-height:1.05;font-variant-numeric:tabular-nums}
.mid{font-size:clamp(17px,3.2vw,24px);font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gap{font-size:clamp(26px,6vw,46px);font-weight:800;font-variant-numeric:tabular-nums}
.row{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.span2{grid-column:span 2}.span4{grid-column:span 4}
.bar{height:8px;background:var(--bg);border-radius:4px;margin:8px 0 6px;overflow:hidden}
.bar>div{height:100%;background:var(--acc);border-radius:4px;width:0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:3px 7px;font-size:12px;font-variant-numeric:tabular-nums}
.radio{font-size:14px;line-height:1.35}
.radio p{padding:5px 0;border-bottom:1px solid var(--line)}
.radio p:last-child{border:none}
.radio b{color:var(--acc);font-size:11px;margin-right:6px}
.radio .q b{color:var(--info)}
.wait{display:flex;align-items:center;justify-content:center;height:70vh;color:var(--muted);text-align:center;font-size:16px;line-height:1.5}
@media (max-width:700px) and (orientation:portrait){.grid{grid-template-columns:repeat(2,1fr)}.span4{grid-column:span 2}}
</style></head><body>
<div class="top"><div class="dot" id="dot"></div><div><div class="title" id="title">Race Engineer</div><div class="sub" id="sub">verbinden…</div></div>
<button class="fs" id="fsbtn">Volledig scherm</button></div>
<div class="flag" id="flag"></div>
<div id="wait" class="wait">Wachten op iRacing…<br>Start een sessie en stap in de auto.</div>
<div id="dash" style="display:none">
<div class="grid">
  <div class="card"><div class="cap">Positie</div><div class="big" id="pos">–</div><div class="sub" id="pos_s"></div></div>
  <div class="card"><div class="cap">Ronde</div><div class="big" id="lap">–</div><div class="sub" id="lap_s"></div></div>
  <div class="card"><div class="cap">Laatste</div><div class="big" id="last" style="font-size:clamp(22px,5vw,40px)">–</div><div class="sub" id="last_s"></div></div>
  <div class="card"><div class="cap">Beste</div><div class="big" id="best" style="font-size:clamp(22px,5vw,40px)">–</div><div class="sub" id="best_s"></div></div>
  <div class="card span2"><div class="cap">Voor je</div><div class="row"><div class="mid" id="a_n">–</div><div class="gap" id="a_g"></div></div><div class="sub" id="a_t"></div></div>
  <div class="card span2"><div class="cap">Achter je</div><div class="row"><div class="mid" id="b_n">–</div><div class="gap" id="b_g"></div></div><div class="sub" id="b_t"></div></div>
  <div class="card span2"><div class="cap">Brandstof &amp; strategie</div><div class="row"><div class="mid" id="fuel">–</div><div class="sub" id="fpl"></div></div><div class="bar"><div id="fbar"></div></div><div class="sub" id="plan"></div></div>
  <div class="card span2"><div class="cap">Coaching · laatste ronde per bocht</div><div class="chips" id="chips"></div><div class="sub" id="weather" style="margin-top:8px"></div></div>
  <div class="card span4"><div class="cap">Boordradio</div><div class="radio" id="radio"></div></div>
</div></div>
<script>
const $=id=>document.getElementById(id);
const sec=(x,d=1)=>Math.abs(x).toFixed(d).replace('.',',');
const lapt=t=>{if(!t||t<=0)return'–';const m=Math.floor(t/60),s=(t-m*60).toFixed(1).padStart(4,'0');return m+':'+s.replace('.',',')};
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
$('fsbtn').onclick=()=>{const d=document.documentElement;(d.requestFullscreen||d.webkitRequestFullscreen||function(){}).call(d)};
const FLAGS={"safety car":["#FFD400","#1A1500","SAFETY CAR"],"geel":["#FFD400","#1A1500","GELE VLAG"],"blauw":["#2F7BFF","#fff","BLAUWE VLAG"],"zwart":["#000","#fff","ZWARTE VLAG"],"wit":["#F2F2F2","#111","LAATSTE RONDE"]};
function side(d,ahead,pre){
  if(!d){$(pre+'_n').textContent='–';$(pre+'_g').textContent='';$(pre+'_t').textContent='niemand';return}
  $(pre+'_n').textContent=d.naam;
  const g=d.gap;$(pre+'_g').textContent=g==null?'…':sec(g)+'s';
  const close=g!=null&&Math.abs(g)<1;
  $(pre+'_g').style.color=close?(ahead?'var(--good)':'var(--bad)'):'var(--text)';
  let t='',c='var(--muted)';const tr=d.trend;
  if(d.pit){t='in de pits';c='var(--info)'}
  else if(tr!=null&&Math.abs(tr)>=0.05){
    if(ahead){[t,c]=tr<0?['je pakt '+sec(tr)+' s/ronde','var(--good)']:['loopt '+sec(tr)+' s/ronde weg','var(--bad)']}
    else{[t,c]=tr>0?['komt '+sec(tr)+' s/ronde dichterbij','var(--bad)']:['je loopt '+sec(tr)+' s/ronde weg','var(--good)']}
  } else if(d.zones){t=d.zones}
  else if(d.laatste){t='laatste ronde '+lapt(d.laatste)}
  $(pre+'_t').textContent=t;$(pre+'_t').style.color=c;
}
let fails=0;
async function tick(){
  try{
    const r=await fetch('/api',{cache:'no-store'});const d=await r.json();fails=0;
    const st=d.status||{};const on=d.actief;
    $('dot').style.background=!on?'#555c66':(st.verbonden?'var(--good)':'var(--acc)');
    $('title').textContent=st.baan?((st.sessie||'')+' · '+st.baan):'Race Engineer';
    let sub=!on?'engineer staat uit':(st.positie?(st.auto||''):'wachten op iRacing');
    const w=st.weer||{};if(w.baantemp!=null)sub+=' · baan '+Math.round(w.baantemp)+'°'+(w.baan?' · '+w.baan:'');
    $('sub').textContent=sub;
    const SPOT={2:"◀ AUTO LINKS",3:"AUTO RECHTS ▶",4:"◀ DRIE BREED ▶",5:"◀◀ TWEE LINKS",6:"TWEE RECHTS ▶▶"};
    const flag=st.incident_actief?["#FF5A5F","#fff","SPIN · KIJK UIT VOOR VERKEER"]:(SPOT[st.spotter]?["#FF8A00","#15100A",SPOT[st.spotter]]:FLAGS[st.vlag]);
    if(flag&&on){$('flag').style.display='block';$('flag').style.background=flag[0];$('flag').style.color=flag[1];
      $('flag').textContent=flag[2]+(st.vlag==='safety car'?(st.pits_open?' · PITS OPEN':' · PITS DICHT'):'')}else $('flag').style.display='none';
    if(!st.positie){$('wait').style.display='flex';$('dash').style.display='none';
      $('wait').innerHTML=on?'Wachten op iRacing…<br>Start een sessie en stap in de auto.':'De engineer staat uit.<br>Start hem in het programma op je pc.';}
    else{$('wait').style.display='none';$('dash').style.display='block';
      $('pos').textContent='P'+st.positie;
      let ps='van '+st.deelnemers+' · '+(st.incidenten||0)+'x'+(st.limiet?'/'+st.limiet:'');
      if(st.irating!=null&&(st.sessie||'').toLowerCase().startsWith('race'))ps+=' · '+(st.irating>=0?'+':'−')+Math.abs(Math.round(st.irating))+' iR';
      $('pos_s').textContent=ps;
      $('lap').textContent=st.ronde+(st.totaal?'/'+st.totaal:'');
      $('lap_s').textContent=st.ronden_te_gaan!=null?'nog '+Math.round(st.ronden_te_gaan)+' ronden':'';
      $('last').textContent=lapt(st.laatste);$('best').textContent=lapt(st.beste);
      if(st.laatste&&st.beste){const dd=st.laatste-st.beste;$('last_s').textContent=dd>0.001?'+'+sec(dd,2)+' t.o.v. beste':'beste ronde!';$('last').style.color=dd<=0.001?'var(--good)':'var(--text)'}
      side(st.voor,true,'a');side(st.achter,false,'b');
      if(st.brandstof!=null){$('fuel').textContent=sec(st.brandstof)+' L'+(st.ronden_in_tank!=null?' · '+sec(st.ronden_in_tank)+' ronden':'');
        $('fpl').textContent=st.verbruik?sec(st.verbruik,2)+' L/ronde':'verbruik meten…';
        $('fbar').style.width=Math.max(0,Math.min(100,st.brandstof/(d.tank||100)*100))+'%'}
      const v=st.venster||[];$('plan').textContent=st.stops===0?'Je haalt de finish zonder stop.':(st.stops?st.stops+' stop nodig · venster ronde '+v[0]+'–'+v[1]+(st.pitstop_klaar?' · klaar: '+st.pitstop_klaar+' L':''):'');
      const b=st.bochten||{};$('chips').innerHTML=Object.keys(b).sort((x,y)=>x-y).map(k=>{const x=b[k];const c=x<-0.02?'var(--good)':(x>0.05?'var(--bad)':'var(--muted)');return `<span class="chip" style="color:${c}">B${k} ${x>0?'+':'−'}${sec(x,2)}</span>`}).join('')||'<span class="sub">na je eerste schone ronde</span>';
      $('weather').textContent=w.regen>0.05?'Regen: '+Math.round(w.regen*100)+'%':'';
    }
    $('radio').innerHTML=(d.radio||[]).slice(-6).reverse().map(m=>`<p class="${m.k==='question'?'q':''}"><b>${m.k==='question'?'JIJ':m.t}</b>${esc(m.x)}</p>`).join('');
  }catch(e){fails++;if(fails>3){$('dot').style.background='var(--bad)';$('sub').textContent='geen verbinding met de pc'}}
  setTimeout(tick,300);
}
tick();
</script></body></html>
"""
