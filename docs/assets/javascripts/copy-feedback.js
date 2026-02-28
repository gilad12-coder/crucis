document.addEventListener("click", function (e) {
  var btn = e.target.closest(".md-code__button");
  if (!btn || btn.getAttribute("data-md-type") !== "copy") return;
  btn.classList.add("md-code__button--copied");
  btn.setAttribute("title", "Copied!");
  setTimeout(function () {
    btn.classList.remove("md-code__button--copied");
    btn.setAttribute("title", "Copy to clipboard");
  }, 1500);
});
