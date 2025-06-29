# AutoCoin 배포 가이드 (Ubuntu 22.04 기준)

> **목적**: 리눅스 경험이 적은 사용자를 위한 단계별 배포·운영 안내서입니다.
> Docker Compose + GitHub Actions CI/CD를 사용합니다.

---

## 1. 서버 준비

| 단계 | 명령 | 설명 |
|------|------|------|
| 패키지 업데이트 | `sudo apt update && sudo apt upgrade -y` | 최신 보안 패치 적용 |
| 필수 도구 설치 | `sudo apt install -y git curl unzip ufw` | git, curl, UFW 방화벽 |
| 방화벽 설정 | `sudo ufw allow 22/tcp && sudo ufw --force enable` | SSH(22)만 허용 후 기본 차단 |

---

## 2. Docker & Compose 설치
```bash
# 1) Docker 엔진 설치
curl -fsSL https://get.docker.com | sudo sh

# 2) Compose v2 플러그인 설치
sudo apt install -y docker-compose-plugin

# 3) Docker 그룹 권한 부여(재로그인 필요)
sudo usermod -aG docker $USER
exit  # → SSH 재접속
```

---

## 3. 프로젝트 디렉터리 & 코드
```bash
# 1) 배포 경로 생성
sudo mkdir -p /opt/autocoin
sudo chown $USER:$USER /opt/autocoin

# 2) 레포지토리 클론
cd /opt/autocoin
git clone https://github.com/tgparkk/AutoCoin.git .
```

---

## 4. 환경 변수 설정
```bash
cp env.example .env   # 템플릿 복사
nano .env             # 값 입력
```
필수 키 · 예시
```
UPBIT_ACCESS_KEY=your_key
UPBIT_SECRET_KEY=your_secret
TELEGRAM_TOKEN=telegram_bot_token  # 선택
TELEGRAM_CHAT_ID=123456789         # 선택
STRATEGY=scalping                  # ma_cross / rsi / advanced_scalping 가능
```

---

## 5. 컨테이너 빌드 & 실행
```bash
docker compose up -d --build  # 백그라운드 기동

docker compose logs -f --tail 100  # 실시간 로그 확인
```
컨테이너 이름은 `autocoin` 으로 자동 지정되며, `--restart unless-stopped` 옵션으로 서버 재부팅 후 자동 기동됩니다.

---

## 6. 코드 업데이트 & 재배포
```bash
cd /opt/autocoin
git pull                  # 최신 코드 가져오기
docker compose down       # 기존 컨테이너 중단
docker compose up -d --build  # 새 이미지 빌드 + 기동
```

---

## 7. 디스크 정리(선택)
```bash
docker system prune -af   # 사용 안 하는 이미지·캐시 삭제
```

---

## 8. GitHub Actions 자동 배포 설정 (선택)

1. **Deploy Key**
   ```bash
   cat ~/.ssh/id_rsa.pub
   ```
   - GitHub ▸ *Settings* ▸ *Deploy keys* ▸ *Add key* (Write 권한 체크)

2. **Secrets 등록** – 레포지토리 *Settings* ▸ *Secrets and variables* ▸ *Actions*
   | 변수 | 예시 값 | 설명 |
   |------|---------|------|
   | REGISTRY_URL | `docker.io` 또는 `ghcr.io/<user>` | Docker 레지스트리 |
   | REGISTRY_USERNAME | `dockerhub_id` | 레지스트리 로그인 ID |
   | REGISTRY_PASSWORD | `********` | PAT 또는 PW |
   | SSH_HOST | `1.2.3.4` | 서버 IP |
   | SSH_USER | `ubuntu` | 접속 계정 |
   | SSH_KEY | *~/.ssh/id_rsa* | 개인키 내용(-----BEGIN 으로 시작) |
   | SSH_PORT | `22` | 포트(옵션) |
   | DEPLOY_DIR | `/opt/autocoin` | 서버 설치 경로 |

3. **배포 흐름**
   1. `master` 브랜치에 푸시
   2. GitHub Actions → 테스트 → Docker 이미지 빌드·푸시
   3. SSH로 서버 접속 후 `docker pull` + `docker compose up -d --build`

배포 로그는 GitHub *Actions* 탭에서 확인할 수 있습니다.

---

## 9. 트러블슈팅
| 증상 | 해결 방법 |
|------|-----------|
| 컨테이너 재시작 반복 | `docker compose logs autocoin` 로 오류 확인 |
| 텔레그램 봇 미동작 | `.env` `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` 확인 |
| 포트 제한으로 WebSocket 실패 | 서버 방화벽 외부 차단 여부 확인(UFW/Cloud) |

---

## 부록: 주요 명령 요약
```bash
# 서비스 상태
docker compose ps

# 실시간 로그
docker compose logs -f --tail 100

# 컨테이너 재시작
docker compose restart
```

> 본 가이드는 지속 갱신됩니다. 개선 아이디어는 Pull Request로 환영합니다! 