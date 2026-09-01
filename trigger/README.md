# 예약 실행 트리거

평일 16:37 KST(07:37 UTC)에 `daily-collect` 워크플로를 깨우는 Cloudflare
Worker. 하는 일은 GitHub dispatch API 를 한 번 호출하는 것뿐이고, 수집과
커밋과 알림은 전부 Actions 안에서 일어난다.

## 왜 GitHub 의 schedule 을 안 쓰나

2026-08-28 에 cron 을 넣은 뒤 예정 슬롯이 여섯 번 지나갔는데 한 번도
발화하지 않았다. 같은 워크플로를 `workflow_dispatch` 로 부르면 매번
정상 실행된다.

| 계기 | 실적 |
|---|---|
| `push` | 10/10 성공 |
| `workflow_dispatch` | 12/12 성공 |
| `schedule` | 예정 슬롯 6회 중 0회 발화 |

저장소는 fork 도 archived 도 아니고, 워크플로 상태는 `active` 이며,
GitHub Actions 상태 페이지에도 인시던트가 없었다. 실행 시각을 옮겨도
달라지지 않았다. 원인은 끝내 못 찾았고, 이 Worker 는 원인을 고치는 것이
아니라 우회한다.

전체 경위는
`docs/superpowers/specs/2026-09-01-cloudflare-cron-trigger-design.md` 에 있다.

## 처음 배포하기

Cloudflare 무료 플랜으로 충분하고 카드 등록도 필요 없다.

1. Cloudflare 계정을 만든다 — https://dash.cloudflare.com/sign-up

2. 의존성을 받고 로그인한다. 브라우저가 열리고 권한을 묻는다.

   ```bash
   cd trigger
   npm install
   npx wrangler login
   ```

3. GitHub fine-grained PAT 을 발급한다 —
   https://github.com/settings/personal-access-tokens/new

   - Repository access: **Only select repositories** → `market-indicator-tracker`
   - Permissions → Repository permissions → **Actions: Read and write**
   - 그 외 권한은 주지 않는다. Expiration 을 반드시 설정한다.

   classic token 은 쓰지 않는다. 계정의 모든 저장소로 권한이 열린다.

4. 토큰을 Worker 비밀값으로 넣는다. 값은 프롬프트에 붙여 넣는다 — 셸
   히스토리에 남기지 않기 위해서다.

   ```bash
   npx wrangler secret put GITHUB_TOKEN
   ```

5. 배포한다.

   ```bash
   npx wrangler deploy
   ```

## 손으로 한 번 깨워보기

cron 을 기다리지 않고 `scheduled` 핸들러를 직접 부른다.

`wrangler dev`는 로컬에서 도는 것이라 `wrangler secret put`으로 배포한
비밀값(`GITHUB_TOKEN`)을 못 본다 — 그건 배포된 Worker 에만 있다. 로컬
실행은 대신 `trigger/.dev.vars` 파일에서 변수를 읽으므로, 이 파일을 먼저
만들어야 한다:

```bash
echo 'GITHUB_TOKEN=<토큰>' > trigger/.dev.vars
```

이 파일은 토큰을 평문으로 담으므로 커밋하면 안 된다 — `.gitignore`에
이미 올라가 있으니 실수로 올라갈 일은 없지만, 다른 이름으로 복사하거나
옮기지 말 것. 이 절차를 마쳤으면 지운다.

한 터미널에서:

```bash
cd trigger && npx wrangler dev --test-scheduled
```

다른 터미널에서:

```bash
curl "http://localhost:8787/__scheduled?cron=37+7+*+*+1-5"
```

첫 터미널 로그에 `dispatch 성공` 이 찍히고, 곧 Actions 에 실행이 생긴다.
여기서 401 이 나면 `.dev.vars`가 없거나 토큰 값이 비어 있다는 뜻이지,
Worker 에 배포된 토큰이 잘못됐다는 뜻이 아니다 — 재발급하기 전에
`.dev.vars`부터 확인할 것.

## 토큰이 만료되면

dispatch 가 401 로 실패하고 Worker 로그에 남지만, 아무도 로그를 보지
않는다. 그래서 실행이 멈춘 것은 healthchecks.io 알림으로 알게 된다 —
`notify_daily.py` 가 매 실행 끝에 ping 을 보내고, 평일 16:47 KST 까지
ping 이 없으면 저쪽에서 알린다.

알림을 받으면 먼저 `npx wrangler tail` 로 Worker 로그를 본다.

## 실행 로그 보기

```bash
npx wrangler tail
```
