/* F-143: couples the radius slider to the numeric #radius field (the only submitted value). Same-origin file; no inline script. */
(function () {
  var n = document.getElementById("radius"), r = document.getElementById("radius_r"), o = document.getElementById("radius-out"), box = document.getElementById("radius-slide");
  if (!n || !r || !o || !box) return;
  box.hidden = false;
  var max = Number(r.max);
  function show() { o.textContent = n.value === "" ? "no limit" : Number(n.value) + " miles"; }
  r.addEventListener("input", function () { n.value = r.value; show(); });
  n.addEventListener("input", function () { var x = Number(n.value); if (n.value !== "" && isFinite(x)) r.value = Math.min(Math.max(x, 0), max); show(); });
  show();
})();
