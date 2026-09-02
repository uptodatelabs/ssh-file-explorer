"""explorer.py 자가 테스트: 서버를 스레드로 띄우고 API 전체를 호출해 본다."""
import json
import os
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

import explorer

TOKEN = "testtoken123"
BASE = "http://127.0.0.1:8777"


def call(method, path, body=None):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    tmp = tempfile.mkdtemp(prefix="wexplorer_test_")
    server = explorer.make_server("127.0.0.1", 8777, tmp, TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(extra) if extra else ""))
        ok = ok and cond

    # 인증
    s, _ = call("GET", "/api/list")
    check("토큰 없이 접근 시 401", s == 401, s)

    q = "?token=" + TOKEN

    # 루트 페이지
    req = urllib.request.urlopen(BASE + "/?" + "t=" + TOKEN)
    html = req.read().decode()
    check("메인 페이지 200 + HTML", req.status == 200 and "<html" in html)

    # 목록
    s, d = call("GET", "/api/list" + q)
    check("목록 조회", s == 200 and d["ok"] and isinstance(d["items"], list))

    # 경로 탈출 시도 차단
    s, d = call("GET", "/api/list" + q + "&path=../../Windows")
    check("경로 탈출 차단", s == 403 or (s == 200 and not d.get("ok")), f"{s} {d if isinstance(d,str) else (d.decode('utf-8','replace') if isinstance(d,bytes) else d.get('error',''))}")

    # 쓰기 + 읽기
    s, d = call("POST", "/api/write" + q, {"path": "hello.txt", "content": "안녕 world"})
    check("파일 저장", s == 200 and d["ok"])
    s, d = call("GET", "/api/read" + q + "&path=hello.txt")
    check("파일 읽기(UTF-8 왕복)", s == 200 and d["content"] == "안녕 world")

    # 폴더 생성
    s, d = call("POST", "/api/mkdir" + q, {"path": "sub/dir"})
    check("폴더 생성(중간까지)", s == 200 and d["ok"])
    s, d = call("GET", "/api/list" + q + "&path=sub")
    check("생성된 폴더 목록", s == 200 and d["items"][0]["name"] == "dir")

    # 이름 변경
    s, d = call("POST", "/api/rename" + q, {"path": "hello.txt", "newname": "hello2.txt"})
    check("이름 변경", s == 200 and d["ok"])
    s, d = call("GET", "/api/read" + q + "&path=hello2.txt")
    check("변경 후 읽기", s == 200)

    # 다운로드
    try:
        with urllib.request.urlopen(BASE + "/api/download" + q + "&path=hello2.txt") as r:
            raw = r.read()
            cd = r.headers.get("Content-Disposition", "")
        check("다운로드 바이트 일치", raw.decode() == "안녕 world" and "hello2.txt" in cd)
    except Exception as e:  # noqa: BLE001
        check("다운로드", False, e)

    # 업로드 (multipart)
    boundary = "----testboundary"
    parts = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"up.txt\"\r\n"
        f"Content-Type: text/plain\r\n\r\nuploaded content\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(BASE + "/api/upload" + q, data=parts, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req) as r:
        up = json.loads(r.read())
    check("multipart 업로드", up["ok"] and up["saved"] == ["up.txt"])
    s, d = call("GET", "/api/read" + q + "&path=up.txt")
    check("업로드 내용 검증", d["content"] == "uploaded content")

    # 검색
    s, d = call("GET", "/api/list" + q + "&q=hello")
    check("검색", s == 200 and any(i["name"] == "hello2.txt" for i in d["items"]))

    # 삭제
    s, d = call("POST", "/api/delete" + q, {"paths": ["up.txt", "sub"]})
    check("파일+폴더 삭제", s == 200 and d["ok"])
    s, d = call("GET", "/api/read" + q + "&path=up.txt")
    check("삭제 후 404", s == 404 or not d.get("ok"))

    # 대용량 스트리밍 헤더 (tmp 루트에 실제 존재하는 파일로 검증)
    req = urllib.request.Request(BASE + "/api/download" + q + "&path=hello2.txt", method="GET")
    with urllib.request.urlopen(req) as r:
        check("다운로드 스트리밍 헤더", r.status == 200 and int(r.headers["Content-Length"]) > 0)

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n=== 결과:", "ALL PASS" if ok else "SOME FAILED", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
