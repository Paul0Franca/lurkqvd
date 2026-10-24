// Tema antes da 1ª pintura (sem piscar o claro). Mesma regra de src/lib/tema.ts.
// Arquivo à parte (e não inline no index.html) para a política de segurança (CSP) proibir scripts inline.
(function () {
  var p = null;
  try { p = localStorage.getItem("lurkqvd.tema"); } catch { /* armazenamento bloqueado: segue o sistema */ }
  var escuro = p === "escuro" || (p !== "claro" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.tema = escuro ? "escuro" : "claro";
})();
