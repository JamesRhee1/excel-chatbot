# 배포 가이드

로컬 systemd 운영과 Streamlit Community Cloud 공개 데모 배포를 다룹니다.
배포 토폴로지 다이어그램은 [README.md](README.md)의 «배포 토폴로지» 절을 참고하세요.

---

## A. Tailscale + systemd (로컬 상시 운영)

로컬/사설망 서버에서 Excel Chatbot을 24시간 운영하기 위한 안내입니다.
앱 동작·의존성은 배포 자산 추가만으로 바뀌지 않습니다.

### A.1 개요

- **Tailscale 사설망**에만 바인딩하고, **systemd**로 Streamlit을 상시 구동합니다.
- 공유기 포트포워딩으로 공인 인터넷에 노출하지 않습니다.
- 이유 요약: (1) 앱에 로그인/인증이 없어 공개 시 누구나 업로드·질의가 가능하고, (2) 공격 표면이 커지며, (3) 공인 IP·서비스 존재가 외부에 드러납니다.

### A.2 사전 요구사항

| 항목 | 권장 |
|---|---|
| OS | Ubuntu / Debian 계열 |
| RAM | **8GB+** (`qwen2.5:7b` 기준) |
| Python | 3.10+ (프로젝트 `requires-python`) |
| Ollama | 설치 후 `ollama pull qwen2.5:7b` |
| Tailscale | [설치 가이드](https://tailscale.com/download) — 스크립트가 자동 설치하지 않음 |

Ollama 서비스 유닛 이름(`ollama.service`)이 시스템에 있어야 `excel-chatbot.service`의 `Requires=`가 충족됩니다.

### A.3 설치

```bash
git clone https://github.com/JamesRhee1/excel-chatbot.git
cd excel-chatbot
./deploy/install.sh --bind 0.0.0.0
```

예시 (Tailscale로 한정):

```bash
./deploy/install.sh --bind 100.x.y.z
```

기본값: `--user` = 현재 사용자, `--dir` = 저장소 루트, `--bind` = `0.0.0.0`.  
신뢰 가능한 LAN 전제입니다. 외부 공개는 금지하고, 필요 시 Tailscale IP로 바인딩을 한정하세요.

설치 스크립트가 하는 일:

1. `.venv`가 없으면 생성 후 `pip install -e .`
2. `deploy/*.service` / `*.timer` 플레이스홀더 치환 → `/etc/systemd/system/` 복사
3. `systemctl enable --now excel-chatbot` 및 트레이스 정리 타이머 활성화

### A.4 운영 명령

| 목적 | 명령 |
|---|---|
| 상태 | `systemctl status excel-chatbot` |
| 로그 | `journalctl -u excel-chatbot -f` |
| 재시작 | `sudo systemctl restart excel-chatbot` |
| 중지 | `sudo systemctl stop excel-chatbot` |
| 트레이스 타이머 | `systemctl status excel-chatbot-trace-cleanup.timer` |
| 가동 검증 | `bash deploy/smoke_test.sh` (11항목) |

### 업데이트

```bash
cd /path/to/excel-chatbot
git pull
.venv/bin/pip install -e .
sudo systemctl restart excel-chatbot
```

### 모델 교체 (`OLLAMA_MODEL`)

유닛 파일을 직접 고치지 말고 오버라이드를 사용합니다.

```bash
sudo systemctl edit excel-chatbot
```

예시 내용:

```ini
[Service]
Environment=OLLAMA_MODEL=qwen2.5:3b
```

저장 후:

```bash
sudo systemctl daemon-reload
sudo systemctl restart excel-chatbot
```

모델 강등 후에는 `python evals/run_evals.py`로 품질을 다시 확인하는 것을 권장합니다.

### A.5 보안 체크리스트

- [ ] `EXCEL_CHATBOT_ENABLE_CODEGEN` **미설정** 유지 (상시 운영 시 codegen 비활성)
- [ ] `--server.address`는 신뢰 LAN의 `0.0.0.0` 또는 **Tailscale IP**로 한정 — 공인 인터넷 노출 금지
- [ ] `maxUploadSize` 20MB 유지
- [ ] `traces/` 30일 초과 `traces_*.jsonl` 자동 삭제 타이머 활성 확인
- [ ] 외부 공개가 필요해지면 Cloudflare Tunnel + Access 등 **별도 인증 계층**을 검토 (이 저장소 범위 밖)

### A.6 트러블슈팅

### Ollama 미기동 (`Requires=` 실패)

```text
Dependency failed for Excel Chatbot
```

- `systemctl status ollama`로 Ollama 기동 여부 확인
- `sudo systemctl start ollama` 후 `sudo systemctl start excel-chatbot`

### 포트 8501 점유

```bash
ss -ltnp | grep 8501
# 또는
sudo lsof -i :8501
```

다른 Streamlit/프로세스를 종료한 뒤 `sudo systemctl restart excel-chatbot`.

### 메모리 부족

- 유닛의 `MemoryMax=4G`를 `systemctl edit`로 조정하거나
- `OLLAMA_MODEL=qwen2.5:3b`로 강등한 뒤 eval을 재확인합니다.

---

## B. Streamlit Community Cloud (공개 데모)

공개 URL로 데모를 제공할 때의 절차입니다. 로컬 systemd 운영과 용도가 다릅니다.

| 구분 | 로컬 (systemd + Ollama) | Streamlit Cloud |
|---|---|---|
| LLM | Ollama (데이터 로컬) | Gemini (`GEMINI_API_KEY`) 또는 데모 모드 |
| 인증 | Tailscale/LAN 한정 | 공개 URL (업로드 주의) |
| 설치 | `deploy/install.sh` | GitHub 연동 + `requirements.txt` |
| 상시 구동 | systemd | Cloud 런타임 (무료 티어 휴면 가능) |

### B.1 배포 절차

1. [share.streamlit.io](https://share.streamlit.io)에서 GitHub 저장소 `JamesRhee1/excel-chatbot` 연결
2. Main file: `ui/app.py`
3. `requirements.txt`는 `-e ".[dev,cloud]"`로 `google-generativeai` 포함 설치
4. **Secrets**에 `GEMINI_API_KEY` 설정 (Settings → Secrets):

```toml
GEMINI_API_KEY = "your-api-key"
```

5. Deploy 후 앱 URL 확인

`ui/app.py` 시작 시 Secrets의 키가 `os.environ`에 주입되며, Ollama는 Cloud에서
사용할 수 없으므로 `get_provider()`는 Gemini → 데모 순으로 선택합니다.

### B.2 무료 티어 특성

- 일정 시간 미사용 시 앱이 슬립 상태로 전환될 수 있습니다 (첫 접속 시 콜드 스타트).
- `GEMINI_API_KEY` 미설정 시 **데모 모드**: 정형 규칙 질의만 동작, 복합 자연어는 안내 메시지.
- 업로드 파일은 세션 단위이며, 공개 URL이므로 민감 데이터 업로드는 권장하지 않습니다.

### B.3 Cloud 설정 파일

`.streamlit/config.toml`:

```toml
[server]
maxUploadSize = 20

[browser]
gatherUsageStats = false
```

---

## C. 공통 품질 확인

```bash
pytest
python evals/run_evals.py --no-llm --strict
bash deploy/smoke_test.sh   # 로컬 systemd 환경에서만 해당
```

