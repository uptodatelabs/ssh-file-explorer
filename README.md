# Web Explorer (SSH 웹 파일 탐색기)

SSH로 접속한 디바이스에서 실행하면, 로컬 브라우저에서 그 디바이스의 파일을
탐색·편집·업로드·다운로드할 수 있는 **단일 파일** 웹 파일 탐색기입니다.

## 동작 방식

1. 디바이스에 SSH로 접속한다.
2. `python3 explorer.py` 를 실행한다.
3. 콘솔에 접속 주소(토큰 포함)가 출력된다.
4. 그 주소를 로컬 브라우저에 입력하면 웹 파일 탐색기가 열린다.

## 사용법

```bash
python3 explorer.py [rootdir] [--port 8080] [--host 0.0.0.0] [--no-token]
```

- `rootdir` : 공개할 폴더 (기본: 현재 폴더)
- `--port`  : 서버 포트 (기본 8080)
- `--host`  : 바인딩 주소 (기본 0.0.0.0)
- `--no-token` : 토큰 인증 끄기 (기본은 랜덤 토큰 인증)

의존성: **Python 3.8+ 표준 라이브러리만** 사용 (pip 설치 불필요)

## 기능

- 폴더 탐색 / 이름 검색 / 숨김 파일 표시
- 텍스트 파일 편집 (저장, Ctrl+S)
- 이미지 미리보기
- 파일/폴더 업로드 (드래그 앤 드롭 지원)
- 파일 다운로드
- 폴더 생성 / 이름 변경 / 삭제
- 토큰 인증 (기본) + root 밖 경로 접근 차단

## API 계약

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

## 테스트

```bash
python3 test_explorer.py
```

서버를 스레드로 띄워 API 전체를 검증한다. (ALL PASS 확인)
