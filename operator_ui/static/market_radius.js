/* F-143: couples the radius slider to the numeric #radius field (the only submitted value). Same-origin file; no inline script. */
(function () {
  var n = document.getElementById("radius"), r = document.getElementById("radius_r"), o = document.getElementById("radius-out"), box = document.getElementById("radius-slide");
  if (!n || !r || !o || !box) return;
  box.hidden = false;
  var base = 500, mx = document.getElementById("radius-max");
  function show() { o.textContent = n.value === "" ? "no limit" : Number(n.value) + " miles"; }
  function range(x) { var m = Math.max(base, Math.ceil(x)); r.max = m; if (mx) mx.textContent = m.toLocaleString("en-US") + " miles"; }  /* F-144: widen, never clamp */
  r.addEventListener("input", function () { n.value = r.value; show(); });
  n.addEventListener("input", function () { var x = Number(n.value); if (n.value !== "" && isFinite(x) && x >= 0) { range(x); r.value = x; } show(); });
  if (n.value !== "" && isFinite(Number(n.value))) { range(Number(n.value)); r.value = Number(n.value); }
  show();
})();
/* F-157: "All categories" ticks/unticks every category box; unticking any one box unticks All. Without this script the server treats All as everything. */
(function () {
  var box = document.getElementById("mkcats");
  if (!box) return;
  var all = box.querySelector("input[value=all]"), rest = box.querySelectorAll("input:not([value=all])");
  all.addEventListener("change", function () { for (var i = 0; i < rest.length; i++) rest[i].checked = all.checked; });
  for (var i = 0; i < rest.length; i++) rest[i].addEventListener("change", function () { if (!this.checked) all.checked = false; });
})();
/* DealSniffer sources are genuinely multi-select. "All sources" changes every
   checkbox immediately; excluding one source immediately clears All. */
(function () {
  var box = document.getElementById("sec-source");
  if (!box) return;
  var all = box.querySelector("input[name=source][value=all]"), rest = box.querySelectorAll("input[name=source]:not([value=all])");
  if (!all) return;
  all.addEventListener("change", function () { for (var i = 0; i < rest.length; i++) rest[i].checked = all.checked; });
  for (var i = 0; i < rest.length; i++) rest[i].addEventListener("change", function () {
    if (!this.checked) all.checked = false;
    else {
      var every = true;
      for (var j = 0; j < rest.length; j++) if (!rest[j].checked) { every = false; break; }
      all.checked = every;
    }
  });
})();
/* Bright Data jobs are asynchronous.  The first request returns the cached
   feed quickly; while the provider finishes, re-check the same snapshot
   without freezing the Search button or starting another paid job. */
(function () {
  if (!document.getElementById("facebook-refresh-pending")) return;
  window.setTimeout(function () { window.location.reload(); }, 6000);
})();
/* F-163: Sort and View apply on change (the Search button does the same without script). */
(function () {
  var s = document.querySelectorAll("select[name=sort],select[name=view]");
  for (var i = 0; i < s.length; i++) s[i].addEventListener("change", function () { if (this.form) this.form.submit(); });
})();
/* The filter controls live outside #mkform and point back to it with the HTML
   form attribute.  Chromium normally serializes those controls correctly, but
   an explicit submit path makes the large search box deterministic: clicking
   Search or pressing Enter always sends its current text, while Apply Filters
   does not request a paid provider refresh. */
(function () {
  var form = document.getElementById("mkform"), search = form && form.querySelector("input[name=keywords]");
  if (!form || !search || !window.FormData || !window.URLSearchParams) return;
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var params = new URLSearchParams(new FormData(form));
    var submitter = event.submitter;
    if (!submitter || (submitter.classList && submitter.classList.contains("mk-go"))) params.set("go", "1");
    else params.delete("go");
    window.location.assign(form.action + "?" + params.toString());
  });
})();
