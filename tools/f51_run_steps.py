# executed inside tools/f51_browser.py (names: pg, base, log, out, app); compares the DOM with an independent computation on the same cache
from datetime import datetime, timezone
from operator_ui import market_search as ms
data = ms.load_gsa(None, datetime.now(timezone.utc))
log["cache"] = {"path": ms.cache_path(), "as_of": data["as_of"], "age_h": data["age_h"], "stale": data["stale"], "lots_in_scope": data["in_scope"], "lots_in_file": data["in_file"]}
shot = lambda name: pg.screenshot(path=str(out / f"{name}.png"), full_page=True, clip={"x": 0, "y": 0, "width": 1280, "height": 1500})  # noqa: E731
def titles(sel):
    return pg.eval_on_selector_all(sel + " .mk-res h3", "els=>els.map(e=>e.firstChild.textContent.trim())")
def main_titles():
    return pg.evaluate("""()=>{const sec=document.getElementById('unchecked-section');const all=[...document.querySelectorAll('.mk-main .mk-res')];
      const f=e=>e.querySelector('h3').firstChild.textContent.trim();return {main:all.filter(e=>!sec||!sec.contains(e)).map(f),unchecked:all.filter(e=>sec&&sec.contains(e)).map(f)}}""")
def expect(**kw):
    q = ms.parse_query({k: [str(v)] for k, v in kw.items()})
    r, u, h = ms.partition(ms.load_gsa(None, datetime.now(timezone.utc), ms._origin(q["base"]))["cards"], q)
    return {"main": [c["title"] for c in r], "unchecked": [c["title"] for c in u]}
def check(name, **kw):
    got, want = main_titles(), expect(**kw)
    heading = pg.inner_text(".mk-main h2")
    log[name] = {"filters": kw, "heading": heading, "dom": got, "expected": want, "match": sorted(got["main"]) == sorted(want["main"]) and sorted(got["unchecked"]) == sorted(want["unchecked"])}
    shot(name)
# 1 default view (no filters): trailers/equipment near Conway
pg.goto(base + "/market"); check("01-default-trailers-equipment-near-conway", broad="", any="trailer, equipment", radius=150, base="Conway AR")
log["chips_default"] = pg.inner_text("#applied-filters")
# 2 type min/max/radius in the real form, click the visible Search button, broad inventory so price/radius effects are visible
def run(base_="Conway AR", radius="", mn="", mx="", broad=True, any_=None):
    pg.goto(base + "/market")
    if base_ is not None: pg.fill("input[name=base]", base_)
    pg.fill("input[name=radius]", str(radius)); pg.fill("#min_price", str(mn)); pg.fill("#max_price", str(mx))
    if any_ is not None: pg.fill("input[name=any]", any_)
    (pg.check if broad else pg.uncheck)("input[name=broad]")
    pg.click(".mk-go"); pg.wait_for_load_state()
kw = lambda **k: {"broad": "1", "base": "Conway AR", **k}  # noqa: E731
run(radius=150, mn=1, mx=20000);   check("02-broad-150mi-1-to-20000", **kw(radius=150, min_price=1, max_price=20000))
run(radius=150, mn=100, mx=500);   check("03-broad-150mi-100-to-500", **kw(radius=150, min_price=100, max_price=500))
run(radius=150, mn=100, mx=100000);   check("04-broad-150mi-min100", **kw(radius=150, min_price=100, max_price=100000))
run(radius=75, mn="", mx="");      check("05-broad-75mi", **kw(radius=75))
run(radius=1, mn="", mx="");       check("06-broad-1mi-zero-known-distance", **kw(radius=1))
run(base_="Zzyzx 99999", radius=50); check("07-unresolved-origin", **kw(base="Zzyzx 99999", radius=50))
run(radius=150, mn=1, mx=20000, broad=False, any_="trailer, equipment"); check("08-focus-trailers-equipment-150mi", radius=150, base="Conway AR", any="trailer, equipment", min_price=1, max_price=20000)
# 3 accessible slider (no scripts: CSP): keyboard on the max slider, then Search; the moved slider is the control used
pg.goto(base + "/market"); pg.check("input[name=broad]"); pg.fill("input[name=radius]", "150"); pg.focus("#max_r"); pg.keyboard.press("Home")
for _ in range(100): pg.keyboard.press("ArrowRight")
shot("09a-slider-keyboard-before-search"); pg.click(".mk-go"); pg.wait_for_load_state()
log["slider_keyboard"] = {"aria": pg.get_attribute("#max_r", "aria-label"), "chips": pg.inner_text("#applied-filters"), "max_slider_after": pg.input_value("#max_r"), "max_box_after": pg.input_value("#max_price")}
check("09-slider-max-101", **kw(radius=150, max_price=101)); 
# 4 persistence across navigation
run(radius=100, mn=20, mx=30); pg.goto(base + "/wanted"); pg.click("a[href='/market']") if pg.query_selector("a[href='/market']") else pg.goto(base + "/market")
log["persisted_chips"] = pg.inner_text("#applied-filters"); shot("10-persisted-after-nav")
# 5 demo not in the normal workflow; separate explicit route
log["normal_pages_contain_demo_link"] = {p_: ("demo=1" in (pg.goto(base + p_) and pg.content())) for p_ in ("/market", "/wanted", "/gsa")}
pg.goto(base + "/demo"); shot("11-demo-separate-route")
# 6 Search + saved actions operable after the fix
pg.goto(base + "/market"); log["search_button_after"] = pg.evaluate("""()=>{const b=document.querySelector('.mk-go');const s=getComputedStyle(b);return {disabled:b.disabled,opacity:s.opacity,color:s.color,bg:s.backgroundColor,cursor:s.cursor}}""")
pg.focus(".mk-go"); shot("12-search-button-focus")
log["save_button_after"] = pg.evaluate("""()=>{const b=[...document.querySelectorAll('button')].find(x=>/Save this search/.test(x.textContent));const s=getComputedStyle(b);return {disabled:b.disabled,opacity:s.opacity,color:s.color,bg:s.backgroundColor}}""")
