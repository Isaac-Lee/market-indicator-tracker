# Cloudflare Worker 트리거 이관 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 발화하지 않는 GitHub `schedule` 대신 Cloudflare Worker가 평일 16:37 KST에 `daily-collect` 워크플로를 깨우고, 실행이 멈추면 healthchecks.io가 알린다.

**Architecture:** Worker는 dispatch API를 한 번 호출하는 것이 전부다. 수집·커밋·텔레그램·Pages 배포는 실적 12/12인 `workflow_dispatch` 경로를 그대로 쓴다. `notify_daily.py`가 실행 끝에 healthchecks로 ping을 보내, 어느 층에서 끊기든 침묵이 알림이 되게 한다.

**Tech Stack:** Cloudflare Workers (JavaScript, ESM), wrangler 4.127.1, Python 3.11, requests

**Spec:** `docs/superpowers/specs/2026-09-01-cloudflare-cron-trigger-design.md`

## Global Constraints

- 트리거 시각은 `37 7 * * 1-5` (07:37 UTC = 16:37 KST, 평일). GitHub cron과 Cloudflare cron 둘 다 UTC 기준이다.
- 비밀값은 저장소에 커밋하지 않는다. `GITHUB_TOKEN`은 `wrangler secret`, `HEALTHCHECK_URL`은 GitHub Actions secret에 넣는다.
- PAT는 fine-grained, 대상 저장소는 `market-indicator-tracker` 하나, 권한은 `Actions: read and write` 하나. classic token은 쓰지 않는다.
- 파이썬 테스트는 pytest가 아니다. `python test_<모듈>.py`로 직접 돌리고, 파일 끝의 `__main__` 블록이 `test_`로 시작하는 함수를 전부 호출한다. 네트워크를 타지 않는 순수 로직만 검증한다.
- 저장소 문서와 주석은 한국어로 쓴다. 커밋 메시지는 영어로 쓴다.
- 사용자 규칙: 코드를 고치면 README도 같은 커밋에 갱신한다.

## Worker에 단위 테스트를 두지 않는 이유

Worker 코드에는 검증할 순수 로직이 사실상 없다 — 상수를 조립해 `fetch`를 한 번 부르는 것이 전부다. 여기에 vitest와 `@cloudflare/vitest-pool-workers`를 들이면 프로젝트에 없던 JS 테스트 인프라가 통째로 생기는데, 그것이 잡아줄 버그가 없다.

대신 Task 4에서 실제 검증을 한다: `--test-scheduled`로 핸들러를 깨워 dispatch가 나가는지, Actions 실행이 실제로 생기는지, 그 실행의 `SKIP_KIS`가 `0`인지. 이 셋이 Worker에 대해 알아야 할 전부다.

파이썬 쪽 ping은 순수 로직이 있으므로 TDD로 간다.

---

### Task 1: healthchecks ping

**Files:**
- Modify: `notify_daily.py`
- Create: `test_notify.py`
- Modify: `README.md` (환경변수 표에 `HEALTHCHECK_URL` 추가)

**Interfaces:**
- Consumes: `kis_client.read_key(label, env_var)` — 환경변수 우선, 없으면 `API-KEY.txt`의 `<label>: 값` 줄에서 읽고, 못 찾으면 `None`
- Produces:
  - `healthcheck_target(url: str, ok: bool) -> str` — ping 보낼 주소
  - `ping_healthcheck(ok: bool) -> None` — 실제 전송, 예외를 삼킨다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`test_notify.py`를 새로 만든다.

```python
"""python test_notify.py — 네트워크 없이 순수 로직만 검증."""
from notify_daily import healthcheck_target


def test_healthcheck_target():
    base = "https://hc-ping.com/abc-123"
    # 성공이면 주소 그대로
    assert healthcheck_target(base, True) == base
    # 실패면 /fail 을 붙여 즉시 알린다 — 기한까지 기다리지 않는다
    assert healthcheck_target(base, False) == base + "/fail"
    # 끝의 슬래시가 //fail 을 만들면 안 된다
    assert healthcheck_target(base + "/", False) == base + "/fail"
    assert healthcheck_target(base + "/", True) == base


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
```

- [ ] **Step 2: 실패하는지 확인한다**

Run: `/usr/bin/python3 test_notify.py`
Expected: FAIL — `ImportError: cannot import name 'healthcheck_target' from 'notify_daily'`

- [ ] **Step 3: 최소 구현을 넣는다**

`notify_daily.py`의 `send_telegram` 함수 바로 뒤에 추가한다. `send_telegram`이 토큰 없을 때 건너뛰는 방식을 그대로 따른다.

```python
def healthcheck_target(url, ok):
    """성공이면 주소 그대로, 실패면 /fail 을 붙인 주소."""
    base = url.rstrip("/")
    return base if ok else base + "/fail"


def ping_healthcheck(ok):
    """실행이 끝났음을 healthchecks.io 에 알린다.

    정해진 시각까지 ping 이 없으면 저쪽에서 알림을 보낸다. 트리거가 무엇이든,
    어느 층에서 끊기든 침묵 자체가 신호가 되는 구조라, 이 줄이 이번 사고
    ("사흘 동안 멈춘 줄 몰랐다")를 되풀이하지 않게 하는 유일한 장치다.

    ping 이 실패해도 수집 결과를 뒤집지 않는다 — 지표는 이미 받아서 파일에
    썼고, 알림을 못 보낸 것이 수집 실패는 아니다.
    """
    url = read_key(r"Healthcheck\s*URL", "HEALTHCHECK_URL")
    if not url:
        print("[건너뜀] HEALTHCHECK_URL 없음", file=sys.stderr)
        return
    try:
        requests.post(healthcheck_target(url, ok), timeout=10)
    except requests.RequestException as exc:
        print(f"[주의] healthcheck ping 실패: {exc}", file=sys.stderr)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `/usr/bin/python3 test_notify.py`
Expected: PASS — `ok test_healthcheck_target`

- [ ] **Step 5: main() 에서 부른다**

`notify_daily.py`의 `main()` 끝부분을 이렇게 바꾼다.

```python
    print(text)
    send_telegram(text)
    ping_healthcheck(rc == 0)
    sys.exit(rc)
```

- [ ] **Step 6: 기존 테스트가 안 깨졌는지 본다**

Run: `/usr/bin/python3 test_collect.py && /usr/bin/python3 test_notify.py`
Expected: 두 파일 모두 `ok ...` 줄만 나오고 예외 없음

- [ ] **Step 7: README 환경변수 표에 한 줄 추가한다**

`README.md` 359~362행의 표는 "`1`이면" 열을 쓰고 있어 URL 변수와 맞지 않는다. 표 바로 아래에 문단으로 붙인다.

```markdown
`HEALTHCHECK_URL`은 값이 `1`인지가 아니라 주소 자체를 쓴다. 실행이 끝나면 이
주소로 ping 을 보내고, 수집이 실패했으면 `/fail` 을 붙여 보낸다. 비어 있으면
ping 을 건너뛰므로 로컬 실행이 남의 체크를 때리지 않는다.
```

- [ ] **Step 8: 커밋한다**

```bash
git add notify_daily.py test_notify.py README.md
git commit -m "Report each run to a healthcheck so silence becomes an alert

The scheduled collection stopped for three days and nobody noticed, which is
the part worth fixing: a run that never starts sends no failure message. A
ping on the way out turns that silence into an alert, whatever stopped it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: daily.yml 에서 죽은 트리거를 걷어낸다

**Files:**
- Modify: `.github/workflows/daily.yml`
- Modify: `README.md` (4절, 7절)

**Interfaces:**
- Consumes: Task 1의 `HEALTHCHECK_URL` 환경변수 (`notify_daily.py`가 읽는다)
- Produces: `workflow_dispatch` 하나가 유일한 실행 계기가 된 워크플로. Task 3의 Worker가 이것을 호출한다

- [ ] **Step 1: schedule 블록을 지운다**

`.github/workflows/daily.yml`에서 아래 8줄을 통째로 지운다.

```yaml
  schedule:
    # 07:37 UTC = 16:37 KST, 평일. 분을 정시에서 멀리 둔 건 취향이 아니라,
    # GitHub 의 schedule 큐가 매시 정각 근처에서 가장 붐비고 그때 트리거가
    # 늦거나 아예 유실되기 때문이다. 실제로 :10 으로 두었을 때 정시 발화가
    # 한 번도 없었다.
    - cron: "37 7 * * 1-5"
```

`on:` 은 이렇게 시작하게 된다.

```yaml
on:
  # 예약 실행은 Cloudflare Worker 가 workflow_dispatch 로 깨운다. GitHub 의
  # schedule 은 이 저장소에서 여섯 슬롯 연속 발화하지 않았고, 같은 파일이
  # dispatch 로는 매번 돌았다. 자세한 경위는 trigger/README.md 참고.
  #
  # push 는 빌드가 깨지지 않았는지 보는 것이라, 실행에 영향을 주지 않는 것만
  # 바뀌었으면 돌릴 이유가 없다.
  push:
```

- [ ] **Step 2: SKIP_KIS 조건식에서 죽은 가지를 걷어낸다**

`schedule`이 사라졌으므로 `github.event_name != 'schedule'`은 영원히 참이다. 남겨두면 읽는 사람을 속인다.

바꾸기 전:

```yaml
          SKIP_KIS: ${{ (github.event_name != 'schedule' && (github.event_name == 'push' || inputs.skip_kis)) && '1' || '0' }}
```

바꾼 뒤 (위의 주석 두 줄도 함께 교체한다):

```yaml
          # push(빌드 테스트)는 KIS 알림톡을 막기 위해 무조건 건너뛴다.
          # workflow_dispatch 는 입력값을 따르고, Worker 는 skip_kis: "false" 를
          # 보내므로 예약 실행은 전체 수집이 된다.
          SKIP_KIS: ${{ (github.event_name == 'push' || inputs.skip_kis) && '1' || '0' }}
```

- [ ] **Step 3: HEALTHCHECK_URL 을 env 에 넘긴다**

같은 스텝의 `env:` 블록에서 `TELEGRAM_CHAT_ID` 줄 바로 아래에 추가한다.

```yaml
          HEALTHCHECK_URL: ${{ secrets.HEALTHCHECK_URL }}
```

- [ ] **Step 4: YAML 이 유효한지 확인한다**

Run: `/usr/bin/python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/daily.yml')); print(sorted(d[True].keys()))"`
Expected: `['push', 'workflow_dispatch']` — `schedule`이 없고 나머지 둘은 남아 있다

(YAML에서 맨 앞의 `on:` 키는 파이썬에서 불리언 `True`로 읽힌다. 오타가 아니다.)

- [ ] **Step 5: README 4절을 고쳐 쓴다**

218~226행 부근의 "## 4. 자동 실행" 절 첫 문단을 아래로 바꾼다.

```markdown
## 4. 자동 실행

**평일 16:37(KST)에 Cloudflare Worker 가 GitHub Actions 를 깨운다**
(`trigger/`, `.github/workflows/daily.yml`). 수집·커밋·텔레그램·Pages 배포는
전부 Actions 안에서 돌고, Worker 는 시각이 되면 실행을 요청하는 일만 한다.

GitHub 자체 `schedule` 은 쓰지 않는다. 이 저장소에서 예정 슬롯 여섯 번이
연속으로 발화하지 않았고, 같은 워크플로가 `workflow_dispatch` 로는 매번
정상 실행됐다. 경위는 `docs/superpowers/specs/2026-09-01-cloudflare-cron-trigger-design.md`
에 적어 두었다.

`data/`가 저장소에 커밋되므로 실행할 때마다 Actions 가 결과를 다시 커밋해
푸시한다 — 이게 유일한 실행 지점이면 된다.
```

- [ ] **Step 6: README 7절 제목과 트리거 표를 고친다**

364~378행 부근이다. 제목과 첫 문단, 표를 아래로 바꾼다.

```markdown
## 7. GitHub Actions (실행 담당)

`.github/workflows/daily.yml`이 `notify_daily.py` → `build_dashboard.py`를
실행하고 `data/`, `docs/`를 커밋·푸시한다. 언제 도는지는 Actions 가 정하지
않는다 — `trigger/` 의 Worker 가 정한다.

두 가지 계기로 도는데 하는 일이 다르다.

| 계기 | KIS 수집 | 텔레그램 | 결과 커밋 |
|---|---|---|---|
| `workflow_dispatch` | 입력값 `skip_kis`에 따라 (Worker 는 전체 수집으로 부른다) | O | O |
| `push` (코드 올릴 때) | X | X (`DRY_RUN`) | X |
```

기존 7절에서 시각이 `:37`인 이유를 설명하던 문단은 지운다 — 그 가설은 틀린 것으로 판명됐고, 이제 시각을 정하는 주체도 GitHub 이 아니다.

- [ ] **Step 7: 커밋한다**

```bash
git add .github/workflows/daily.yml README.md
git commit -m "Stop pretending GitHub schedules this workflow

Six consecutive scheduled slots produced no run while dispatch succeeded every
time, so the cron block described something that does not happen. Leaving it in
would tell the next reader the collection fires at 16:37 on its own.

Removing it also makes the event_name check in SKIP_KIS dead weight, so that
goes too, and the healthcheck URL from the previous commit gets passed through.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Worker

**Files:**
- Create: `trigger/src/index.js`
- Create: `trigger/wrangler.toml`
- Create: `trigger/package.json`
- Create: `trigger/README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 2가 남긴 `workflow_dispatch` 계기와 `skip_kis` 입력
- Produces: `market-indicator-trigger` Worker. cron `37 7 * * 1-5`에 `daily.yml`을 dispatch 한다. 비밀값 이름은 `GITHUB_TOKEN`

- [ ] **Step 1: package.json 을 만든다**

`trigger/package.json`:

```json
{
  "name": "market-indicator-trigger",
  "private": true,
  "devDependencies": {
    "wrangler": "^4.127.1"
  }
}
```

- [ ] **Step 2: wrangler.toml 을 만든다**

`trigger/wrangler.toml`:

```toml
name = "market-indicator-trigger"
main = "src/index.js"
compatibility_date = "2026-09-01"

# 07:37 UTC = 16:37 KST. Cloudflare 의 cron 도 UTC 기준이고, 요일 1-5 는
# 월~금이다. 한국 공휴일에는 장이 열리지 않는데도 깨우지만, 그때는 수집이
# 빈 결과를 받을 뿐이라 그대로 둔다.
[triggers]
crons = ["37 7 * * 1-5"]
```

- [ ] **Step 3: Worker 코드를 쓴다**

`trigger/src/index.js`:

```js
// 이 Worker 가 하는 일은 하나다 — 시각이 되면 GitHub 에 "그 워크플로 좀
// 돌려달라"고 요청한다. 수집도, 커밋도, 알림도 전부 Actions 안에서 일어난다.
//
// 왜 GitHub 의 schedule 을 안 쓰는지는 trigger/README.md 참고.

const OWNER = "Isaac-Lee";
const REPO = "market-indicator-tracker";
const WORKFLOW = "daily.yml";

async function dispatch(env) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub API 는 User-Agent 없는 요청을 403 으로 거절한다.
      "User-Agent": "market-indicator-trigger",
    },
    // dispatch API 는 입력값을 문자열로만 받는다. 워크플로가 skip_kis 를
    // type: boolean 으로 선언해 두어서 GitHub 이 이 "false" 를 boolean 으로
    // 바꿔주고, 그 덕에 예약 실행이 KIS 계열까지 전부 수집한다.
    body: JSON.stringify({ ref: "main", inputs: { skip_kis: "false" } }),
  });

  // 성공은 204 No Content 다. 그 외에는 본문에 이유가 들어 있으니 남긴다 —
  // 토큰 만료가 여기로 온다.
  if (res.status !== 204) {
    console.error(`dispatch 실패 ${res.status}: ${await res.text()}`);
    return;
  }
  console.log("dispatch 성공");
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
};
```

- [ ] **Step 4: .gitignore 에 node_modules 를 넣는다**

`.gitignore` 끝에 추가한다. (기존 파일에 `API-KEY.txt`가 두 번 적혀 있는데, 이번 작업과 무관하므로 건드리지 않는다.)

```
trigger/node_modules/
```

- [ ] **Step 5: trigger/README.md 를 쓴다**

```markdown
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

cron 을 기다리지 않고 `scheduled` 핸들러를 직접 부른다. 한 터미널에서:

```bash
cd trigger && npx wrangler dev --test-scheduled
```

다른 터미널에서:

```bash
curl "http://localhost:8787/__scheduled?cron=37+7+*+*+1-5"
```

첫 터미널 로그에 `dispatch 성공` 이 찍히고, 곧 Actions 에 실행이 생긴다.

## 토큰이 만료되면

dispatch 가 401 로 실패하고 Worker 로그에 남지만, 아무도 로그를 보지
않는다. 그래서 실행이 멈춘 것은 healthchecks.io 알림으로 알게 된다 —
`notify_daily.py` 가 매 실행 끝에 ping 을 보내고, 평일 16:40 KST 까지
ping 이 없으면 저쪽에서 알린다.

알림을 받으면 먼저 `npx wrangler tail` 로 Worker 로그를 본다.

## 실행 로그 보기

```bash
npx wrangler tail
```
```

- [ ] **Step 6: 문법이 깨지지 않았는지 본다**

Run: `cd trigger && npm install && npx wrangler deploy --dry-run`
Expected: 번들링이 성공하고 `--dry-run` 이라 실제 배포는 하지 않는다는 메시지. 문법 오류가 있으면 여기서 잡힌다.

(`npx wrangler login` 전이라도 `--dry-run` 은 계정 없이 돈다. 안 되면 Task 4의 로그인을 먼저 하고 돌아온다.)

- [ ] **Step 7: 커밋한다**

```bash
git add trigger .gitignore
git commit -m "Add the Worker that will wake the collection

It does one thing: ask GitHub to run the workflow. Everything else stays in
Actions, on the dispatch path that has worked every time. Deploying it is a
separate step — this commit only puts the code and the setup instructions in
the repository.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: 배포하고 실제로 도는지 확인한다

**Files:** 없음 (외부 서비스 설정과 검증)

**Interfaces:**
- Consumes: Task 3의 Worker 코드, Task 1의 ping, Task 2의 워크플로
- Produces: 살아서 도는 트리거와 감시

이 태스크의 대부분은 사람이 직접 해야 한다. 에이전트는 명령어를 안내하고, 결과를 함께 확인한다.

- [ ] **Step 1: healthchecks.io 체크를 만든다**

https://healthchecks.io 에 가입하고 (무료 플랜으로 충분) 체크를 하나 만든다.

- Name: `market-indicator-tracker daily`
- Schedule: **Cron** 을 고르고 `37 7 * * 1-5`, Time zone `UTC`
- Grace Time: `10 minutes` (16:47 KST 까지 안 오면 알림)

만들면 `https://hc-ping.com/<uuid>` 형태의 ping URL 이 나온다. 이걸 복사한다.

알림 받을 곳도 설정한다. 이메일이 기본이고, Integrations 에서 텔레그램도 붙일 수 있다.

- [ ] **Step 2: ping URL 을 GitHub secret 으로 넣는다**

```bash
gh secret set HEALTHCHECK_URL
```

프롬프트에 URL 을 붙여 넣는다.

- [ ] **Step 3: ping 경로가 실제로 도는지 확인한다**

수동으로 워크플로를 돌린다.

```bash
gh workflow run daily-collect -f skip_kis=false
```

30초쯤 기다린 뒤 결과를 본다.

```bash
gh run list --workflow daily-collect --limit 1
```

Expected: `completed  success`

healthchecks.io 대시보드에서 체크가 방금 ping 을 받았는지 (초록으로 바뀌었는지) 확인한다. 안 받았으면 실행 로그에서 `[건너뜀] HEALTHCHECK_URL 없음` 이 찍혔는지 본다 — 그러면 secret 이 안 들어간 것이다.

- [ ] **Step 4: SKIP_KIS 가 0 인지 눈으로 확인한다**

spec 이 짚은 검증이다. 문자열 `"false"` 가 boolean 으로 변환되는 데 기대고 있어서, 잘못되면 KIS 계열이 조용히 통째로 빈다.

```bash
gh run view "$(gh run list --workflow daily-collect --limit 1 --json databaseId --jq '.[0].databaseId')" --log | grep -i "kis\|코스피\|건너뜀" | head -20
```

Expected: KIS 계열(코스피·코스닥·삼성전자 등)을 실제로 받은 흔적이 보이고, KIS 를 건너뛰었다는 줄은 **없다**.

건너뛴 것으로 나오면 `"false"` 문자열이 boolean 으로 변환되지 않은 것이다. 이 경우 워크플로의 `skip_kis` 입력에서 `type: boolean` 을 빼고 문자열로 받아 `inputs.skip_kis == 'true'` 로 비교하도록 바꾼다. 조용히 넘어가면 안 되는 실패다 — 지표가 비는데 실행은 성공으로 찍힌다.

- [ ] **Step 5: Worker 를 배포한다**

`trigger/README.md` 의 "처음 배포하기" 를 따른다. 요약하면:

```bash
cd trigger
npm install
npx wrangler login
npx wrangler secret put GITHUB_TOKEN   # PAT 을 붙여 넣는다
npx wrangler deploy
```

Expected: 배포 성공 메시지와 함께 cron 트리거가 등록됐다는 줄이 나온다.

- [ ] **Step 6: Worker 를 손으로 깨운다**

한 터미널:

```bash
cd trigger && npx wrangler dev --test-scheduled
```

다른 터미널:

```bash
curl "http://localhost:8787/__scheduled?cron=37+7+*+*+1-5"
```

Expected: 첫 터미널에 `dispatch 성공`. 그리고:

```bash
gh run list --workflow daily-collect --limit 1
```

방금 생긴 `workflow_dispatch` 실행이 보인다. 401 이 나오면 PAT 권한이나 만료를 확인한다.

- [ ] **Step 7: 진짜 검증 — 다음 평일 07:37 UTC 를 기다린다**

앞의 여섯 단계가 전부 통과해도 예약 발화가 안 되면 아무 의미가 없다. 이번 사고가 정확히 그런 모양이었다 — 수동 실행은 매번 됐다.

다음 평일 07:37 UTC (16:37 KST) 이후에 확인한다.

```bash
gh run list --workflow daily-collect --limit 3
```

Expected: 그 시각 근처에 `workflow_dispatch` 실행이 하나 있다. Worker 가 부른 것이라 계기는 `schedule` 이 아니라 `workflow_dispatch` 로 찍힌다.

발화하지 않았으면 `cd trigger && npx wrangler tail` 로 Worker 가 깨어나기는 했는지부터 본다.

- [ ] **Step 8: 커밋할 것은 없다**

이 태스크는 외부 설정과 검증이라 저장소 변경이 없다. 검증 결과를 사람에게 보고하고, Step 7 은 다음 평일까지 열어 둔다.

---

### Task 5: 정리

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 앞선 모든 태스크
- Produces: 없음

- [ ] **Step 1: README 5절의 자체 cron 안내를 손본다**

224~226행 부근에 "자체 cron 이 필요하면 5절 끝의 '매일 갱신에 붙이기' 참고" 라는 문장이 있다. 실행 지점이 하나여야 한다는 취지는 그대로 유효하므로 문장만 새 구조에 맞춘다.

```markdown
로컬/VPS 에서 손으로 또는 cron 으로 병행 실행하면 `data/` 사본이 갈려 서로
덮어쓴다. 자동 실행은 Worker → Actions 한 경로로 두고, 다른 환경은 필요할 때만
손으로 돌린다.
```

- [ ] **Step 2: 트리거 절을 새로 넣는다**

7절 뒤에 붙인다.

```markdown
## 8. 트리거 (Cloudflare Worker)

언제 도는지를 정하는 것은 `trigger/` 의 Worker 다. 평일 16:37 KST 에 깨어나
`daily.yml` 을 dispatch 한다. 배포와 토큰 발급 절차는 `trigger/README.md` 에
있다.

실행이 멈추면 healthchecks.io 가 알린다 — `notify_daily.py` 가 매 실행 끝에
ping 을 보내고, 평일 16:47 KST 까지 ping 이 없으면 알림이 온다. Worker 가
죽든, 토큰이 만료되든, Actions 가 멈추든 침묵 자체가 신호가 된다.
```

- [ ] **Step 3: 문서 안의 죽은 참조를 찾는다**

Run: `grep -n "16:10\|07:10\|schedule (평일\|예약 실행(schedule)" README.md`
Expected: 아무것도 안 나온다. 나오면 그 줄을 새 구조에 맞게 고친다.

- [ ] **Step 4: 커밋한다**

```bash
git add README.md
git commit -m "Point the README at the trigger that actually runs

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
