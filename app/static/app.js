// 파일경로 복사 버튼
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button.copy");
  if (!btn) return;
  await navigator.clipboard.writeText(btn.dataset.copy);
  const label = btn.textContent;
  btn.textContent = "복사됨";
  setTimeout(() => (btn.textContent = label), 1200);
});

// 5초마다 공유폴더 변경 확인 → 바뀌면 자동 새로고침 (입력 화면에서는 안내만)
(() => {
  let rev = Number(document.body.dataset.rev);
  const autoreload = document.body.dataset.autoreload === "1";
  setInterval(async () => {
    try {
      const res = await fetch("/api/rev");
      const data = await res.json();
      if (data.rev !== rev) {
        if (autoreload && !document.querySelector("input:checked[name=ids], textarea:focus, input:focus")) {
          location.reload();
        } else {
          document.getElementById("live-banner").hidden = false;
        }
      }
      rev = data.rev;
    } catch (err) {
      // 프로그램 창이 닫힌 경우 등 — 조용히 다음 주기에 재시도
    }
  }, 5000);
})();
