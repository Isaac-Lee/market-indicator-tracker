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
