// F-160: live countdown on the listing detail page. Display only; the server already rendered the same text.
(function () {
  var el = document.getElementById("dt-cd");
  if (!el || !el.dataset.end) return;
  var end = Date.parse(el.dataset.end);
  if (isNaN(end)) return;
  function tick() {
    var s = Math.max(0, Math.floor((end - Date.now()) / 1000));
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    el.textContent = s === 0 ? "Closed" : d + " days " + h + " hrs " + m + " min " + (s % 60) + " sec";
  }
  tick();
  setInterval(tick, 1000);
})();
