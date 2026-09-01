# 예약 실행을 Cloudflare Worker로 옮긴다

작성일: 2026-09-01

## 왜

`daily-collect` 워크플로가 예정된 시각에 돌지 않는다. 2026-08-28에 cron을
넣은 뒤 평일 슬롯이 세 번 지나갔는데 정시 발화는 한 번도 없었고, 유일하게
기록된 예약 실행 한 건은 예정 시각과 무관한 08-28 19:24 UTC에 잡힌 것이다.

처음에는 GitHub이 매시 정각 근처에서 붐빈다는 설명을 믿고 실행 시각을
`07:10 UTC`에서 `07:37 UTC`로 옮겼다. 다음 날에도 발화하지 않았다. 그 가설은
틀렸다.

원인을 가르기 위해 데이터 파이프라인과 무관한 프로브 워크플로를 만들어
10분 간격 cron을 걸었다. 세 슬롯 연속으로 실행이 생기지 않았다. 같은 파일을
`workflow_dispatch`로 부르면 5초 만에 성공한다.

| 트리거 | 실적 |
|---|---|
| `push` | 10/10 성공 |
| `workflow_dispatch` | 12/12 성공 |
| `schedule` | 예정 슬롯 6회 중 0회 발화 |

저장소는 `fork:false`, `archived:false`, `disabled:false`, public이고 워크플로
상태는 `active`다. GitHub Actions 상태 페이지에도 인시던트가 없다. 워크플로
내용과 실행 경로는 무죄다 — 08-28의 예약 실행은 끝까지 성공했다.

죽은 것은 트리거 생성 단계 하나뿐이다. cron 시각을 어떻게 고쳐도 소용없다는
것이 이제 추측이 아니라 측정값이다.

## 무엇을 만드는가

시각이 되면 GitHub API를 한 번 호출하는 Cloudflare Worker. 그게 전부다.
수집·커밋·알림·배포는 지금 그대로 Actions에서 돌아간다. 실적이 12/12인
경로를 굳이 건드릴 이유가 없다.

```
Cloudflare Worker  (cron: 37 7 * * 1-5 = 평일 16:37 KST)
   │  POST /repos/Isaac-Lee/market-indicator-tracker/actions/workflows/daily.yml/dispatches
   │  body: {"ref":"main","inputs":{"skip_kis":"false"}}
   │  auth: fine-grained PAT (이 저장소 하나, Actions read+write)
   ▼
GitHub Actions  (workflow_dispatch)
   │  notify_daily.py → collect.py → 텔레그램
   │  build_dashboard.py → data/, docs/ 커밋 push
   ▼
healthchecks.io
      성공 시 ping, 실패 시 /fail ping
      평일 16:40 KST까지 ping 없으면 알림
```

### 왜 n8n이 아닌가

트리거만 옮기면 되는 일에 워크플로 엔진과 그것을 얹을 서버를 새로 떠안게
된다. self-host 하면 그 서버가 새로운 단일 장애점이 되어, GitHub 스케줄러를
못 믿어서 옮긴 자리에 똑같이 조용히 죽을 수 있는 것을 하나 세우는 셈이다.
이미 다른 용도로 n8n을 운영 중이라면 판단이 달라지지만, 지금은 아니다.

### 왜 실패 감지를 같이 넣는가

이번 사고의 본질은 예약 실행이 멈춘 것이 아니라 **멈춘 것을 사흘 동안 아무도
몰랐다**는 것이다. 트리거를 Cloudflare로 옮겨도 그 성질은 그대로다. Worker가
죽거나 PAT가 만료되면 똑같이 조용히 멈춘다.

healthchecks.io는 이것을 뒤집는다. 정해진 시각까지 ping이 오지 않으면 알림이
간다. 트리거가 무엇이든, 어느 층에서 끊기든, 침묵 자체가 신호가 된다.

## 건드리는 파일

| 파일 | 변경 |
|---|---|
| `trigger/src/index.js` (신규) | Worker. `scheduled()` 핸들러에서 dispatch 호출 |
| `trigger/wrangler.toml` (신규) | 이름, cron 트리거, 호환 날짜 |
| `trigger/README.md` (신규) | 배포와 비밀값 등록 절차 |
| `notify_daily.py` | healthchecks ping 추가 |
| `.github/workflows/daily.yml` | `schedule:` 제거, `SKIP_KIS` 조건식 정리 |
| `README.md` | 4절·7절 재작성, 트리거 운영 절 추가 |

## 설계 결정

### schedule 블록은 제거한다

여섯 슬롯 0회 발화로 죽은 것이 측정되었다. 남겨두면 파일을 읽는 사람이
"평일 16:37에 도는구나"라고 오해한다. 죽은 설정은 거짓말을 한다. 트리거
주체를 Worker 하나로 명확히 한다.

GitHub이 나중에 복구되어도 되살리지 않는다. 되살리면 트리거가 둘이 되고,
어느 쪽이 돌았는지 추적하기 어려워진다.

### SKIP_KIS 조건식을 정리한다

현재 식은 이렇다.

```
${{ (github.event_name != 'schedule' && (github.event_name == 'push' || inputs.skip_kis)) && '1' || '0' }}
```

`schedule`을 제거하면 `!= 'schedule'`은 영원히 참인 죽은 가지가 된다. 다음에
읽는 사람을 속이므로 같이 지운다.

```
${{ (github.event_name == 'push' || inputs.skip_kis) && '1' || '0' }}
```

동작은 그대로다. push는 빌드 확인이라 KIS를 건너뛰고, dispatch는 입력값을
따른다. Worker는 `skip_kis: "false"`를 명시해서 보내므로 전체 수집이 돈다.

dispatch API는 입력값을 문자열로만 받는다. 워크플로가 `skip_kis`를
`type: boolean`으로 선언해 두었으므로 GitHub이 `"false"` 문자열을 boolean
`false`로 변환하고, `inputs.skip_kis`는 거짓으로 평가된다. 이 변환에 기대는
셈이니 테스트 2단계에서 실행 로그의 `SKIP_KIS` 값이 `0`인지 눈으로 확인한다.
`1`이면 KIS 계열이 통째로 비므로 조용히 넘어가면 안 되는 실패다.

### PAT는 최소 권한으로 좁힌다

fine-grained personal access token을 쓴다.

- 대상 저장소: `market-indicator-tracker` 하나
- 권한: `Actions` read and write 하나
- 만료일: 설정한다. 만료로 트리거가 멈추면 healthchecks가 잡는다

classic token은 쓰지 않는다. 계정 전체 저장소에 권한이 열린다.

### ping은 성공과 실패를 구분한다

`notify_daily.py`의 `main()`은 이미 `collect.py`의 종료 코드를 들고 있다.
성공이면 기본 ping, 실패면 `/fail` ping을 보낸다. 실패를 즉시 알리는 쪽이
"16:40까지 조용하네"를 기다리는 것보다 빠르다.

ping 실패가 수집 결과를 뒤집으면 안 된다. ping은 예외를 삼키고, 종료 코드는
`collect.py`의 것을 그대로 쓴다.

`HEALTHCHECK_URL`은 GitHub secret으로 넣는다. 없으면 ping을 건너뛴다 —
로컬 실행에서 남의 체크를 때리지 않기 위해서다. 텔레그램 전송이 이미 같은
방식으로 토큰 부재를 다루고 있으니 그 패턴을 따른다.

### 공휴일은 이번 범위 밖

Worker cron도 `1-5`로 평일만 돈다. 한국 공휴일에는 장이 열리지 않는데도
실행되지만, 이는 지금 동작과 같고 수집이 빈 결과를 받을 뿐이다. 별도로
다룬다.

## 테스트

1. `wrangler dev --test-scheduled`로 cron 핸들러를 로컬에서 호출해 dispatch가
   실제로 나가는지 확인한다.
2. 배포 후 Worker를 수동으로 한 번 깨워 Actions 실행이 생기는지 확인한다.
3. healthchecks 대시보드에서 ping이 도착했는지 확인한다.
4. 다음 평일 07:37 UTC에 자동 발화를 관찰한다. 이것이 진짜 검증이다 —
   앞의 셋이 모두 통과해도 예약 발화가 안 되면 아무 의미가 없다.

## 사람이 직접 해야 하는 일

자동화할 수 없는 부분이다.

1. Cloudflare 가입 (무료 플랜으로 충분, 카드 등록 불필요)
2. `npm i -D wrangler` 후 `npx wrangler login`
3. GitHub fine-grained PAT 발급 (위 권한대로)
4. `npx wrangler secret put GITHUB_TOKEN`
5. healthchecks.io 가입, check 생성 (평일 16:40 KST 기한), ping URL 확보
6. GitHub 저장소 secret에 `HEALTHCHECK_URL` 등록

## 미해결로 남기는 것

GitHub이 왜 이 저장소에 schedule 트리거를 보내지 않는지는 끝내 모른다.
저장소 설정, 워크플로 내용, 계정 상태, 서비스 상태 어디에서도 원인이 나오지
않았다. 이 설계는 원인을 고치는 것이 아니라 우회하는 것이다.

우회를 택한 근거는 GitHub 자신이 예약 실행의 정시성을 보장하지 않는다고
문서에 밝히고 있다는 점이다. 원인을 알아내도 우리가 고칠 수 있는 종류의
것이 아닐 가능성이 높다.
