# 배포 가이드 (Tailscale + systemd)

로컬/사설망 서버에서 Excel Chatbot을 24시간 운영하기 위한 안내입니다.
앱 동작·의존성은 배포 자산 추가만으로 바뀌지 않습니다.

## 1. 개요

- **Tailscale 사설망**에만 바인딩하고, **systemd**로 Streamlit을 상시 구동합니다.
- 공유기 포트포워딩으로 공인 인터넷에 노출하지 않습니다.
- 이유 요약: (1) 앱에 로그인/인증이 없어 공개 시 누구나 업로드·질의가 가능하고, (2) 공격 표면이 커지며, (3) 공인 IP·서비스 존재가 외부에 드러납니다.

## 2. 사전 요구사항

| 항목 | 권장 |
|---|---|
| OS | Ubuntu / Debian 계열 |
| RAM | **8GB+** (`qwen2.5:7b` 기준) |
| Python | 3.11+ (프로젝트 `.venv`) |
| Ollama | 설치 후 `ollama pull qwen2.5:7b` |
| Tailscale | [설치 가이드](https://tailscale.com/download) — 스크립트가 자동 설치하지 않음 |

Ollama 서비스 유닛 이름(`ollama.service`)이 시스템에 있어야 `excel-chatbot.service`의 `Requires=`가 충족됩니다.

## 3. 설치

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

## 4. 운영 명령

| 목적 | 명령 |
|---|---|
| 상태 | `systemctl status excel-chatbot` |
| 로그 | `journalctl -u excel-chatbot -f` |
| 재시작 | `sudo systemctl restart excel-chatbot` |
| 중지 | `sudo systemctl stop excel-chatbot` |
| 트레이스 타이머 | `systemctl status excel-chatbot-trace-cleanup.timer` |
| 가동 검증 | `bash deploy/smoke_test.sh` |

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

## 5. 보안 체크리스트

- [ ] `EXCEL_CHATBOT_ENABLE_CODEGEN` **미설정** 유지 (상시 운영 시 codegen 비활성)
- [ ] `--server.address`는 신뢰 LAN의 `0.0.0.0` 또는 **Tailscale IP**로 한정 — 공인 인터넷 노출 금지
- [ ] `maxUploadSize` 20MB 유지
- [ ] `traces/` 30일 초과 `traces_*.jsonl` 자동 삭제 타이머 활성 확인
- [ ] 외부 공개가 필요해지면 Cloudflare Tunnel + Access 등 **별도 인증 계층**을 검토 (이 저장소 범위 밖)

## 6. 트러블슈팅

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
