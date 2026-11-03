// Toca media/intro.mp4 por cima do painel sempre que ele abre; ao acabar (ou ao pular), some e libera o painel.
(() => {
  const intro = document.getElementById("intro");
  const video = document.getElementById("intro-video");
  const som = document.getElementById("intro-som");
  let fechada = false;

  function fechar() {
    if (fechada) return;
    fechada = true;
    intro.classList.add("saindo");
    setTimeout(() => { video.pause(); video.removeAttribute("src"); video.load(); intro.remove(); }, 800);
  }

  video.addEventListener("ended", fechar);
  video.addEventListener("error", fechar);
  document.getElementById("intro-pular").addEventListener("click", fechar);
  document.addEventListener("keydown", e => { if (!fechada && (e.key === "Escape" || e.key === "Enter")) fechar(); });

  som.addEventListener("click", () => { video.muted = false; som.hidden = true; });

  // O navegador costuma bloquear vídeo com som antes de um clique; nesse caso toca mudo e oferece o botão de som.
  video.play().catch(() => {
    video.muted = true;
    som.hidden = false;
    video.play().catch(fechar);
  });
})();
