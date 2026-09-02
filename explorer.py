#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
explorer.py -- SSH로 접속해서 실행하면, 브라우저용 웹 파일 탐색기를 띄워주는 단일 파일 도구.

사용법 (디바이스에서):
    python3 explorer.py [rootdir] [--port 8080] [--host 0.0.0.0] [--no-token]

의존성: Python 3.8+ 표준 라이브러리만 사용 (pip install 불필요)

API 계약 (test_explorer.py 가 검증한다):
    GET  /                       -> HTML (토큰: ?t= 또는 ?token=)
    GET  /api/list?path=&q=      -> {ok, root, path, parent, items:[{name,path,dir,size,...}], free}
    GET  /api/read?path=         -> {ok, content, size, size_h, truncated, mtime_h}
    GET  /api/download?path=&dl= -> 파일 바이트 (Content-Disposition 포함)   [/api/raw 별칭]
    POST /api/write   {path, content}
    POST /api/mkdir   {path}            (중간 폴더까지 생성)
    POST /api/rename  {path, newname}
    POST /api/delete  {paths:[...]}
    POST /api/upload  multipart/form-data (field: path, files)
    인증 실패 -> 401, root 밖 경로 -> 403
"""

import argparse
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

# ------------------------------------------------------------------ 기본 설정
DEFAULT_PORT = 8080
DEFAULT_HOST = "0.0.0.0"
MAX_READ = 2 * 1024 * 1024      # 에디터로 열 수 있는 최대 파일 크기
MAX_BODY = 200 * 1024 * 1024    # 업로드 본문 최대 크기
SEARCH_LIMIT = 500
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".svn", ".hg"}

TEXT_EXT = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".scss", ".sh", ".bash", ".zsh", ".c", ".h",
    ".cpp", ".hpp", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".sql", ".ini",
    ".cfg", ".conf", ".env", ".toml", ".log", ".csv", ".tsv", ".gitignore", ".srt",
}


# ------------------------------------------------------------------ 유틸
def lan_ip():
    """이 머신의 LAN IP 추정 (SSH 클라이언트가 실제로 볼 주소)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def is_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except Exception:
        return False


def human(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def posix_join(a, b):
    a = (a or "").replace("\\", "/").rstrip("/")
    b = (b or "").replace("\\", "/").lstrip("/")
    if not a:
        return b
    if not b:
        return a
    return a + "/" + b


def rel_of(root, abs_path):
    p = os.path.realpath(abs_path)
    if p == root:
        return ""
    return os.path.relpath(p, root).replace(os.sep, "/")


def entry_info(root, abs_path, name):
    try:
        st = os.lstat(abs_path)
    except OSError:
        return None
    is_dir = os.path.isdir(abs_path)
    return {
        "name": name,
        "path": rel_of(root, abs_path),
        "dir": is_dir,
        "link": os.path.islink(abs_path),
        "size": 0 if is_dir else st.st_size,
        "size_h": "-" if is_dir else human(st.st_size),
        "mtime": int(st.st_mtime),
        "mtime_h": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        "mode": oct(st.st_mode & 0o777),
        "text": (not is_dir) and is_text(abs_path),
    }


# ------------------------------------------------------------------ HTML (프론트엔드)
HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Web Explorer</title>
<style>
:root{--bg:#12151a;--fg:#dfe3ea;--dim:#8b95a7;--line:#242a33;--acc:#4da3ff}
*{box-sizing:border-box}
body{margin:0;background:#12151a;color:#dfe3ea;font:14px/1.5 -apple-system,"Segoe UI",Roboto,"Malgun Gothic",sans-serif}
header{display:flex;gap:8px;align-items:center;padding:10px 14px;border-bottom:1px solid #242a33;position:sticky;top:0;background:#12151a;z-index:5;flex-wrap:wrap}
header b{color:#4da3ff;font-weight:600}
button{background:#1d232c;color:#dfe3ea;border:1px solid #2c3542;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:13px}
button:hover{background:#273040}
button.pri{background:#1c4ed8;border-color:#1c4ed8;color:#fff}
input,textarea{background:#0d1015;color:#dfe3ea;border:1px solid #2c3542;border-radius:6px;padding:6px 8px;font-size:13px}
#crumbs{display:flex;gap:4px;align-items:center;flex-wrap:wrap;font-size:13px;color:#8b95a7;padding:6px 14px;border-bottom:1px solid #242a33}
#crumbs a{color:#4da3ff;text-decoration:none;cursor:pointer}
#crumbs a:hover{text-decoration:underline}
main{display:grid;grid-template-columns:minmax(320px,1fr) minmax(320px,1fr);gap:0;height:calc(100vh - 92px)}
#left{border-right:1px solid #242a33;overflow:auto;padding:8px}
#right{overflow:auto;display:flex;flex-direction:column}
table{width:100%;border-collapse:collapse}
td,th{padding:5px 8px;text-align:left;white-space:nowrap}
th{color:#8b95a7;font-weight:500;font-size:12px;border-bottom:1px solid #242a33;position:sticky;top:0;background:#12151a}
tr[data-p]:hover{background:#1a2029;cursor:pointer}
tr.sel{background:#16304d}
td.n{max-width:45vw;overflow:hidden;text-overflow:ellipsis}
td.s,td.d{color:#8b95a7;font-size:12px;text-align:right}
.dir .n{color:#ffcc66}.lnk .n{color:#7ee0a5}
#ehead{padding:8px 12px;border-bottom:1px solid #242a33;display:flex;gap:8px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:#12151a}
#ehead span{color:#8b95a7;font-size:12px}
#code{flex:1;width:100%;border:0;outline:0;padding:12px;font:13px/1.55 ui-monospace,Consolas,"D2Coding",monospace;resize:none;background:#0d1015;color:#dfe3ea;white-space:pre;overflow:auto;tab-size:4}
#prev{flex:1;overflow:auto;padding:12px;text-align:center;background:#0d1015}
#prev img{max-width:100%;border-radius:6px}
#empty{color:#8b95a7;padding:40px;text-align:center}
#toast{position:fixed;right:16px;bottom:16px;background:#1c4ed8;color:#fff;padding:10px 14px;border-radius:8px;opacity:0;transition:.25s;pointer-events:none;max-width:70vw}
#toast.on{opacity:1}
#toast.err{background:#c0392b}
.badge{font-size:11px;color:#8b95a7;border:1px solid #2c3542;border-radius:4px;padding:1px 5px}
</style></head><body>
<header>
  <b>WEB EXPLORER</b>
  <span class="badge" id="rootb">__ROOT__</span>
  <button onclick="load(cwd)">새로고침</button>
  <button onclick="up()">../</button>
  <button onclick="mkdir()">+ 폴더</button>
  <button onclick="f.click()">+ 업로드</button>
  <input type="file" id="f" multiple hidden>
  <input id="q" placeholder="이름 검색 (Enter)" style="width:160px" onkeydown="if(event.key==='Enter')load(cwd)">
  <label style="font-size:12px;color:#8b95a7"><input type="checkbox" id="hid" onchange="load(cwd)"> 숨김</label>
  <span id="stat" style="margin-left:auto;font-size:12px;color:#8b95a7"></span>
</header>
<div id="crumbs"></div>
<main>
  <div id="left"><div id="empty">불러오는 중…</div></div>
  <div id="right"><div id="empty">파일을 선택하세요</div></div>
</main>
<div id="toast"></div>
<script>
const TOKEN="__TOKEN__";
let cwd="", cur=null, dirty=false;

function toast(m,e){const t=document.getElementById('toast');t.textContent=m;t.className='on'+(e?' err':'');setTimeout(()=>t.className='',2200);}
function esc(s){return (s+'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function url(p,q){const u=new URL(p,location.origin);u.searchParams.set('token',TOKEN);for(const k in q)u.searchParams.set(k,q[k]);return u;}
async function api(p,q={},opt={}){
  const r=await fetch(url(p,q),opt);
  const j=await r.json().catch(()=>({ok:false,error:r.status+' 요청 실패'}));
  if(!r.ok||j.ok===false) throw new Error(j.error||j.err||('HTTP '+r.status));
  return j;
}
function post(p,body){return api(p,{},{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

async function load(path){
  const query=(document.getElementById('q').value||'').trim();
  let j; try{ j=await api('/api/list',{path:path||'',q:query}); }catch(e){ return toast(e.message,1); }
  cwd=j.path||''; history.replaceState(null,'','#'+encodeURIComponent(cwd));
  document.getElementById('rootb').textContent=j.root;
  const parts=cwd?cwd.split('/'):[], cr=[`<a onclick="load('')">ROOT</a>`];
  let acc='';
  parts.forEach(p=>{acc=acc?acc+'/'+p:p; cr.push(`<span>/</span><a onclick="load('${esc(acc)}')">${esc(p)}</a>`);});
  document.getElementById('crumbs').innerHTML=cr.join('');
  const hid=document.getElementById('hid').checked;
  const es=(j.items||[]).filter(e=>hid||!e.name.startsWith('.'));
  es.sort((a,b)=>(b.dir-a.dir)||a.name.localeCompare(b.name));
  document.getElementById('stat').textContent=`${es.length} 항목 · ${j.free||''}${query?' · 검색: '+query:''}`;
  const rows=es.map(e=>`<tr class="${e.dir?'dir':(e.link?'lnk':'')}" data-p="${esc(e.path)}" data-d="${e.dir?1:0}" data-t="${e.text?1:0}" data-name="${esc(e.name)}">
    <td class="n">${e.dir?'📁':(e.link?'🔗':'📄')} ${esc(e.name)}${query?`<span style="color:#8b95a7;font-size:11px"> ${esc(e.path)}</span>`:''}</td>
    <td class="s">${e.size_h}</td><td class="d">${e.mtime_h}</td>
    <td class="d"><button onclick="ev(event,'dl')">⬇</button> <button onclick="ev(event,'rn')">✎</button> <button onclick="ev(event,'rm')">🗑</button></td></tr>`).join('');
  document.getElementById('left').innerHTML=es.length?`<table><tr><th>이름</th><th>크기</th><th>수정</th><th></th></tr>${rows}</table>`:`<div id="empty">빈 폴더 / 결과 없음</div>`;
  document.querySelectorAll('tr[data-p]').forEach(tr=>{tr.onclick=()=>row(tr);});
}
function row(tr){
  const p=tr.dataset.p; if(!p) return;
  document.querySelectorAll('tr.sel').forEach(x=>x.classList.remove('sel'));
  tr.classList.add('sel');
  if(tr.dataset.d==='1') return load(p);
  cur={path:p,name:tr.dataset.name,text:tr.dataset.t==='1'};
  open(cur);
}
function dlhref(p){const u=url('/api/download',{path:p,dl:1});return u.pathname+u.search;}
async function open(e){
  const R=document.getElementById('right');
  if(!e.text){
    const img=/\.(png|jpe?g|gif|webp|bmp|svg|ico)$/i.test(e.name);
    R.innerHTML=`<div id="ehead"><b>${esc(e.name)}</b><span>텍스트가 아닌 파일</span>
      <button onclick="rawdl()">⬇ 다운로드</button></div>
      <div id="prev">${img?`<img src="${dlhref(e.path)}">`:`<div id="empty">미리보기 없음 — 다운로드하여 확인하세요</div>`}</div>`;
    return;
  }
  R.innerHTML=`<div id="ehead"><b>${esc(e.name)}</b><span id="mi">불러오는 중…</span>
    <button class="pri" onclick="save()">저장</button><button onclick="rawdl()">⬇ 다운로드</button></div>
    <textarea id="code" spellcheck="false"></textarea>`;
  const ta=document.getElementById('code');
  try{
    const j=await api('/api/read',{path:e.path});
    ta.value=j.content; document.getElementById('mi').textContent=`${j.size_h} · ${j.truncated?'⚠ 잘림 · ':''}${j.mtime_h||''}`;
    dirty=false;
  }catch(err){ ta.value=''; toast(err.message,1); }
  ta.oninput=()=>dirty=true;
  ta.onkeydown=ev=>{ if((ev.ctrlKey||ev.metaKey)&&ev.key==='s'){ev.preventDefault();save();} };
}
async function save(){
  if(!cur) return;
  try{
    await post('/api/write',{path:cur.path,content:document.getElementById('code').value});
    dirty=false; toast('저장했습니다: '+cur.name); load(cwd);
  }catch(e){ toast(e.message,1); }
}
function rawdl(){ if(cur) location.href=dlhref(cur.path); }
function up(){ load(cwd.split('/').slice(0,-1).join('/')); }
async function mkdir(){
  const n=prompt('새 폴더 이름','new-folder'); if(!n) return;
  try{ await post('/api/mkdir',{path:posix(cwd,n)}); toast('폴더 생성'); load(cwd);}catch(e){toast(e.message,1);}
}
function posix(a,b){a=(a||'').replace(/\\/g,'/').replace(/\/$/,'');return a?a+'/'+b:b;}
async function ev(ev2,act){
  ev2.stopPropagation();
  const tr=ev2.target.closest('tr'), p=tr.dataset.p, name=tr.dataset.name;
  if(act==='dl') return location.href=dlhref(p);
  if(act==='rn'){ const n=prompt('새 이름',name); if(!n)return;
    try{ await post('/api/rename',{path:p,newname:n}); toast('이름 변경'); load(cwd);}catch(e){toast(e.message,1);} }
  if(act==='rm'){ if(!confirm(`"${name}" 삭제? (폴더면 내용까지)`))return;
    try{ await post('/api/delete',{paths:[p]}); toast('삭제했습니다');
      if(cur&&cur.path===p){cur=null;document.getElementById('right').innerHTML='<div id="empty">파일을 선택하세요</div>';}
      load(cwd);}catch(e){toast(e.message,1);} }
}
async function send(files){
  if(!files.length) return;
  const fd=new FormData(); fd.append('path',cwd);
  for(const x of files) fd.append('files',x,x.name);
  toast(`${files.length}개 업로드 중…`);
  try{
    const r=await fetch(url('/api/upload',{}),{method:'POST',body:fd});
    const j=await r.json().catch(()=>({ok:false,error:'실패'}));
    if(!r.ok||j.ok===false) throw new Error(j.error||j.err||'실패');
    toast('업로드 완료: '+(j.saved||[]).join(', ')); load(cwd);
  }catch(e){ toast(e.message,1); }
}
document.getElementById('f').onchange=e=>send([...e.target.files]);
const L=document.getElementById('left');
L.addEventListener('dragover',e=>{e.preventDefault();L.style.outline='2px dashed #1c4ed8';});
L.addEventListener('dragleave',()=>{L.style.outline=''});
L.addEventListener('drop',e=>{e.preventDefault();L.style.outline='';send([...e.dataTransfer.files]);});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
load(decodeURIComponent(location.hash.slice(1)));
</script></body></html>"""

# ------------------------------------------------------------------ 서버
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WebExplorer/1.0"
    root = os.getcwd()      # make_server() 가 바인딩
    token = ""              # 빈 문자열이면 토큰 인증 끔

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % a))

    # ---- helpers
    def _token_ok(self, q):
        if not self.token:
            return True
        got = (q.get("token") or q.get("t") or [""])[0] or self.headers.get("X-Token", "")
        return bool(got) and secrets.compare_digest(got, self.token)

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _err(self, msg, code=400):
        m = str(msg)
        self._json({"ok": False, "error": m, "err": m}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return b""
        if n > MAX_BODY:
            raise ValueError("본문이 너무 큽니다 (%s)" % human(n))
        return self.rfile.read(n)

    def _json_body(self):
        raw = self._body()
        if not raw:
            return {}
        ctype = self.headers.get("Content-Type", "")
        if "json" not in ctype:
            return {}
        try:
            d = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("JSON 본문이 아닙니다")
        return d if isinstance(d, dict) else {}

    def _safe(self, rel):
        """root 밖으로 나가는 경로(../, 절대경로)를 차단하고 절대경로 반환."""
        rel = (rel or "").replace("\\", "/").lstrip("/")
        target = os.path.realpath(os.path.join(self.root, rel))
        if target != self.root and not target.startswith(self.root + os.sep):
            raise PermissionError("root 밖 접근 금지: %s" % rel)
        return target

    def _rel(self, abs_path):
        return rel_of(self.root, abs_path)

    def _disk(self):
        try:
            u = shutil.disk_usage(self.root)
            return "여유 %s / %s" % (human(u.free), human(u.total))
        except Exception:
            return ""

    # ---- 라우팅
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        if u.path in ("/", "/index.html"):
            if not self._token_ok(q):
                return self._send(403, "유효하지 않은 토큰입니다. 콘솔에 출력된 URL을 그대로 사용하세요.",
                                  "text/plain; charset=utf-8")
            html = HTML.replace("__TOKEN__", self.token or "").replace("__ROOT__", self.root)
            return self._send(200, html, "text/html; charset=utf-8")

        if not self._token_ok(q):
            return self._err("invalid token", 401)

        routes = {
            "/api/list": self.api_list,
            "/api/ls": self.api_list,
            "/api/read": self.api_read,
            "/api/download": self.api_download,
            "/api/raw": self.api_download,
            "/api/stat": self.api_stat,
        }
        fn = routes.get(u.path)
        if not fn:
            return self._err("not found", 404)
        try:
            fn(q)
        except PermissionError as e:
            self._err(e, 403)
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as e:
            self._err("없는 경로: %s" % (getattr(e, "filename", None) or e), 404)
        except Exception as e:
            self._err(e, 500)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        if not self._token_ok(q):
            return self._err("invalid token", 401)
        routes = {
            "/api/write": self.api_write,
            "/api/mkdir": self.api_mkdir,
            "/api/rename": self.api_rename,
            "/api/delete": self.api_delete,
            "/api/upload": self.api_upload,
        }
        fn = routes.get(u.path)
        if not fn:
            return self._err("not found", 404)
        try:
            fn(q)
        except PermissionError as e:
            self._err(e, 403)
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as e:
            self._err("없는 경로: %s" % (getattr(e, "filename", None) or e), 404)
        except Exception as e:
            self._err(e, 500)

    # ---- API: 읽기
    def api_list(self, q):
        rel = (q.get("path") or [""])[0]
        d = self._safe(rel)
        if not os.path.isdir(d):
            raise NotADirectoryError(rel)
        pat = (q.get("q") or [""])[0].strip().lower()
        items = []
        if pat:
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
                for name in dirnames + filenames:
                    if pat in name.lower():
                        info = entry_info(self.root, os.path.join(dirpath, name), name)
                        if info:
                            items.append(info)
                        if len(items) >= SEARCH_LIMIT:
                            break
                if len(items) >= SEARCH_LIMIT:
                    break
        else:
            for name in sorted(os.listdir(d)):
                info = entry_info(self.root, os.path.join(d, name), name)
                if info:
                    items.append(info)
        self._json({
            "ok": True, "root": self.root, "path": self._rel(d),
            "parent": self._rel(os.path.dirname(d.rstrip(os.sep))) if self._rel(d) else "",
            "items": items, "free": self._disk(), "query": pat,
        })

    def api_read(self, q):
        p = self._safe((q.get("path") or [""])[0])
        if os.path.isdir(p):
            raise IsADirectoryError(p)
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            raw = f.read(MAX_READ)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", "replace")
        st = os.stat(p)
        self._json({
            "ok": True, "path": self._rel(p), "content": text, "size": size,
            "size_h": human(size), "truncated": size > len(raw),
            "mtime_h": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        })

    def api_stat(self, q):
        p = self._safe((q.get("path") or [""])[0])
        self._json({"ok": True, "entry": entry_info(self.root, p, os.path.basename(p))})

    def api_download(self, q):
        p = self._safe((q.get("path") or [""])[0])
        if os.path.isdir(p):
            raise IsADirectoryError(p)
        size = os.path.getsize(p)
        name = os.path.basename(p)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        inline = ctype.startswith(("image/", "text/", "application/pdf"))
        disp = "inline" if (inline and not (q.get("dl") or [""])[0]) else "attachment"
        ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         '%s; filename="%s"; filename*=UTF-8\'\'%s' % (disp, ascii_name, quote(name)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(p, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

    # ---- API: 쓰기
    def api_write(self, q):
        b = self._json_body()
        rel = b.get("path") or (q.get("path") or [""])[0]
        p = self._safe(rel)
        if os.path.isdir(p):
            raise IsADirectoryError(rel)
        content = b.get("content")
        if content is None:
            content = b.get("text", "")
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        parent = os.path.dirname(p)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = p + ".we-tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        self._json({"ok": True, "path": self._rel(p), "size": len(data)})

    def api_mkdir(self, q):
        b = self._json_body()
        rel = b.get("path") or (q.get("path") or [""])[0]
        name = (b.get("name") or "").strip().strip("/")
        if name:
            rel = posix_join(rel, name)
        d = self._safe(rel)
        if d == self.root:
            raise PermissionError("루트는 생성 불가")
        os.makedirs(d, exist_ok=True)
        self._json({"ok": True, "path": self._rel(d)})

    def api_rename(self, q):
        b = self._json_body()
        src_rel = b.get("path") or b.get("from") or (q.get("path") or [""])[0]
        dst_rel = b.get("newname") or b.get("to") or ""
        if not dst_rel:
            raise ValueError("newname 이 필요합니다")
        src = self._safe(src_rel)
        if src == self.root:
            raise PermissionError("루트는 변경 불가")
        dst = self._safe(posix_join(os.path.dirname(src_rel.replace("\\", "/")), dst_rel))
        if dst == self.root:
            raise PermissionError("루트로 변경 불가")
        if os.path.exists(dst):
            raise ValueError("이미 존재하는 이름입니다")
        os.rename(src, dst)
        self._json({"ok": True, "path": self._rel(dst)})

    def api_delete(self, q):
        b = self._json_body()
        paths = b.get("paths")
        if not isinstance(paths, list):
            single = b.get("path") or (q.get("path") or [""])[0]
            paths = [single] if single else []
        if not paths:
            raise ValueError("paths 가 비어 있습니다")
        deleted = []
        for rel in paths:
            p = self._safe(rel)
            if p == self.root:
                raise PermissionError("루트는 삭제 불가")
            if not os.path.lexists(p):
                raise FileNotFoundError(rel)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            deleted.append(self._rel(p))
        self._json({"ok": True, "deleted": deleted})

    def api_upload(self, q):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            raise ValueError("multipart/form-data 가 아닙니다")
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m:
            raise ValueError("boundary 없음")
        body = self._body()
        dest_rel = (q.get("path") or [""])[0]
        files, fields = self._parse_multipart(body, m.group(1).encode())
        if not dest_rel:
            dest_rel = fields.get("path", "")
        d = self._safe(dest_rel)
        if not os.path.isdir(d):
            raise NotADirectoryError(dest_rel)
        saved = []
        for fname, data in files:
            fname = os.path.basename(fname.replace("\\", "/"))
            if not fname or fname in (".", ".."):
                continue
            target = os.path.join(d, fname)
            base, ext = os.path.splitext(fname)
            i = 1
            while os.path.exists(target):
                target = os.path.join(d, "%s(%d)%s" % (base, i, ext))
                i += 1
            with open(target, "wb") as f:
                f.write(data)
            saved.append(os.path.basename(target))
        self._json({"ok": True, "path": self._rel(d), "saved": saved})

    @staticmethod
    def _parse_multipart(body, boundary):
        """(files:[(filename, bytes)], fields:{name: value}) 반환."""
        files, fields = [], {}
        delim = b"--" + boundary
        for part in body.split(delim)[1:]:
            if part[:2] == b"--":
                break
            if part[:2] == b"\r\n":
                part = part[2:]
            if part[-2:] == b"\r\n":
                part = part[:-2]
            if not part:
                continue
            head, sep, data = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            hm = re.search(rb'name="([^"]*)"', head, re.I)
            if not hm:
                continue
            field = hm.group(1).decode("utf-8", "replace")
            fm = re.search(rb'filename="([^"]*)"', head, re.I)
            if fm:
                fname = fm.group(1).decode("utf-8", "replace")
                if fname:
                    files.append((fname, data))
            else:
                fields[field] = data.decode("utf-8", "replace")
        return files, fields


# __PART4__

# ------------------------------------------------------------------ 서버 팩토리 / 메인
def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, root=".", token=""):
    """테스트/메인이 공통으로 쓰는 서버 생성 함수.

    반환된 ThreadingHTTPServer 의 Handler 에 root/token 을 바인딩한다.
    """
    root = os.path.realpath(os.path.abspath(root))
    handler = type(str("Bound" + Handler.__name__), (Handler,), {
        "root": root,
        "token": token or "",
    })
    srv = ThreadingHTTPServer((host, port), handler)
    srv.root = root
    srv.token = token or ""
    return srv


def main():
    ap = argparse.ArgumentParser(description="SSH 로 실행하는 웹 파일 탐색기 (단일 파일)")
    ap.add_argument("root", nargs="?", default=".", help="공개할 폴더 (기본: 현재 폴더)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--no-token", action="store_true", help="토큰 인증 끄기")
    a = ap.parse_args()

    root = os.path.realpath(os.path.abspath(a.root))
    if not os.path.isdir(root):
        print("폴더가 없습니다: %s" % root)
        sys.exit(1)
    token = "" if a.no_token else secrets.token_urlsafe(8)

    try:
        srv = make_server(a.host, a.port, root, token)
    except OSError as e:
        print("포트를 열 수 없습니다 (%s:%d): %s" % (a.host, a.port, e))
        sys.exit(1)

    ip = lan_ip()
    tail = ("/?token=" + token) if token else "/"
    ssh_client = (os.environ.get("SSH_CLIENT") or "").split()
    client_ip = ssh_client[0] if ssh_client else ""

    print()
    print("  \033[1m[Web Explorer] 실행\033[0m  root: %s" % root)
    print("  " + "-" * 58)
    print("  브라우저 주소:")
    print("    \033[1;36mhttp://%s:%d%s\033[0m" % (ip, a.port, tail))
    print("    http://127.0.0.1:%d%s" % (a.port, tail))
    if client_ip:
        print()
        print("  SSH 클라이언트(%s)에서 직접 안 되면, PC 에서 터널:" % client_ip)
        print("    ssh -L %d:localhost:%d <user>@<이 디바이스IP>" % (a.port, a.port))
        print("    -> PC 브라우저에서 http://localhost:%d%s" % (a.port, tail))
    if token:
        print()
        print("  토큰: %s  (이 URL 외 접속 불가 / Ctrl+C 로 종료)" % token)
    print("  " + "-" * 58)
    sys.stdout.flush()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  종료합니다.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
