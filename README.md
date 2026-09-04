# Web Explorer (SSH Web File Explorer)

A **single-file** web file explorer that lets you browse, edit, upload, and download
files on a device you reach over SSH — right from your local browser.

---

## English

### Installation (PyPI)

```bash
pip install ssh-file-explorer
```

After installation, run it anywhere with the `explorer` command:

```bash
explorer [rootdir] [--port 8080] [--host 127.0.0.1] [--no-token]
```

> To run from source, clone the repository and run `python3 explorer.py`.

### How it works

1. SSH into the device.
2. Run `python3 explorer.py`.
3. The console prints the access URL (including the token).
4. Open that URL in your local browser to use the web file explorer.

### Usage

```bash
python3 explorer.py [rootdir] [--port 8080] [--host 127.0.0.1] [--no-token]
```

- `rootdir` : folder to expose (default: current folder)
- `--port`  : server port (default 8080)
- `--host`  : bind address (default 127.0.0.1 — loopback only)
- `--no-token` : disable token auth (default: random token auth)

Dependencies: **Python 3.8+ standard library only** (no pip install needed)

### Security

By default the server binds only to the loopback (`127.0.0.1`), so remote access
must go through an **SSH tunnel**.

```bash
# After starting the server on the device, from your local machine:
ssh -L 8080:127.0.0.1:8080 user@device
# Then open http://localhost:8080/ in your browser (traffic is encrypted over SSH)
```

> ⚠️ **Warning**: If you expose it directly to the LAN with `--host 0.0.0.0`,
> the token is sent over **plain HTTP**. Only use this on a trusted network, and
> prefer an SSH tunnel whenever possible.

### Features

- Folder browsing / name search / show hidden files
- Text file editing (save, Ctrl+S)
- Image preview
- File/folder upload (drag & drop support)
- File download
- Create folder / rename / delete
- Token auth (default) + blocks access outside the root

### API contract

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/` | HTML (token: `?t=` or `?token=`) |
| GET  | `/api/list?path=&q=` | Listing `{ok, root, path, parent, items, free}` |
| GET  | `/api/read?path=` | Read text `{ok, content, size, size_h, truncated, mtime_h}` |
| GET  | `/api/download?path=&dl=` | File bytes (Content-Disposition) |
| POST | `/api/write` | `{path, content}` save |
| POST | `/api/mkdir` | `{path}` create folder (including intermediate folders) |
| POST | `/api/rename` | `{path, newname}` rename |
| POST | `/api/delete` | `{paths:[...]}` delete |
| POST | `/api/upload` | multipart/form-data (`path`, `files`) |

Auth failure → 401, path outside root → 403

### Tests

```bash
python3 test_explorer.py
```

Starts the server in a thread and verifies the full API. (Expect ALL PASS)

---

## 한국어

SSH로 접속하는 디바이스의 파일을 로컬 브라우저에서 바로 탐색·편집·업로드·다운로드할
수 있는 **단일 파일** 웹 파일 탐색기입니다.

### 설치 (PyPI)

```bash
pip install ssh-file-explorer
```

설치 후 어디서든 `explorer` 명령으로 실행할 수 있습니다.

```bash
explorer [rootdir] [--port 8080] [--host 127.0.0.1] [--no-token]
```

> 소스에서 직접 실행하려면 저장소를 받아 `python3 explorer.py` 로 실행하면 됩니다.

### 동작 방식

1. 디바이스에 SSH로 접속한다.
2. `python3 explorer.py` 를 실행한다.
3. 콘솔에 접속 주소(토큰 포함)가 출력된다.
4. 그 주소를 로컬 브라우저에 입력하면 웹 파일 탐색기가 열린다.

### 사용법

```bash
python3 explorer.py [rootdir] [--port 8080] [--host 127.0.0.1] [--no-token]
```

- `rootdir` : 공개할 폴더 (기본: 현재 폴더)
- `--port`  : 서버 포트 (기본 8080)
- `--host`  : 바인딩 주소 (기본 127.0.0.1 — 루프백 전용)
- `--no-token` : 토큰 인증 끄기 (기본은 랜덤 토큰 인증)

의존성: **Python 3.8+ 표준 라이브러리만** 사용 (pip 설치 불필요)

### 보안

기본적으로 서버는 루프백(`127.0.0.1`)에만 바인딩되므로, 원격 접근은 반드시
**SSH 터널**을 통해야 합니다.

```bash
# 디바이스에서 서버 실행 후, 로컬에서:
ssh -L 8080:127.0.0.1:8080 user@device
# 브라우저에서 http://localhost:8080/  (트래픽은 SSH로 암호화됨)
```

> ⚠️ **주의**: `--host 0.0.0.0` 로 LAN에 직접 노출하면 토큰이 **평문 HTTP**로
> 전송됩니다. 반드시 신뢰할 수 있는 네트워크에서만 사용하고, 가능하면 SSH 터널을
> 사용하세요.

### 기능

- 폴더 탐색 / 이름 검색 / 숨김 파일 표시
- 텍스트 파일 편집 (저장, Ctrl+S)
- 이미지 미리보기
- 파일/폴더 업로드 (드래그 앤 드롭 지원)
- 파일 다운로드
- 폴더 생성 / 이름 변경 / 삭제
- 토큰 인증 (기본) + root 밖 경로 접근 차단

### API 계약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET  | `/` | HTML (토큰: `?t=` 또는 `?token=`) |
| GET  | `/api/list?path=&q=` | 목록 `{ok, root, path, parent, items, free}` |
| GET  | `/api/read?path=` | 텍스트 읽기 `{ok, content, size, size_h, truncated, mtime_h}` |
| GET  | `/api/download?path=&dl=` | 파일 바이트 (Content-Disposition) |
| POST | `/api/write` | `{path, content}` 저장 |
| POST | `/api/mkdir` | `{path}` 폴더 생성 (중간 폴더까지) |
| POST | `/api/rename` | `{path, newname}` 이름 변경 |
| POST | `/api/delete` | `{paths:[...]}` 삭제 |
| POST | `/api/upload` | multipart/form-data (`path`, `files`) |

인증 실패 → 401, root 밖 경로 → 403

### 테스트

```bash
python3 test_explorer.py
```

서버를 스레드로 띄워 API 전체를 검증한다. (ALL PASS 확인)
