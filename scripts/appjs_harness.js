// A do-nothing browser for running the whole of public/app.js under jsc
// (macOS JavaScriptCore), so a test can call its real functions: prepend this,
// then app.js, then the test's own code (one script, so app.js's top-level
// let/const are in scope). Every element is a stub that keeps what is written
// to it (innerHTML, textContent, attributes); getElementById returns the same
// one per id. Nothing fetches (fetch never answers: the test sets app.js's
// data itself), no timer fires, and storage is an in-memory map.
// Used by scripts/test_home_picks.py.
var __els = {};
function __mkEl(id) {
  var attrs = {}, kids = [];
  var el = {
    id: id || "", innerHTML: "", textContent: "", value: "", hidden: false, checked: false,
    dataset: {}, style: { setProperty: function () {} }, options: [], children: kids, childNodes: kids,
    classList: { _s: {}, add: function (c) { this._s[c] = 1; }, remove: function (c) { delete this._s[c]; },
                 toggle: function (c, f) { if (f === undefined ? !this._s[c] : f) this._s[c] = 1; else delete this._s[c]; },
                 contains: function (c) { return !!this._s[c]; } },
    setAttribute: function (k, v) { attrs[k] = String(v); }, getAttribute: function (k) { return k in attrs ? attrs[k] : null; },
    removeAttribute: function (k) { delete attrs[k]; }, hasAttribute: function (k) { return k in attrs; },
    addEventListener: function () {}, removeEventListener: function () {}, dispatchEvent: function () {},
    appendChild: function (c) { kids.push(c); return c; }, append: function () {}, prepend: function () {}, remove: function () {},
    insertAdjacentHTML: function () {}, replaceWith: function () {}, replaceChildren: function () {},
    querySelector: function () { return null; }, querySelectorAll: function () { return []; }, closest: function () { return null; },
    getBoundingClientRect: function () { return { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }; },
    focus: function () {}, blur: function () {}, scrollIntoView: function () {}, click: function () {},
    offsetHeight: 0, offsetWidth: 0, clientWidth: 0, clientHeight: 0, scrollWidth: 0, isConnected: true,
    parentElement: null, firstChild: null, lastElementChild: null, nextElementSibling: null, firstElementChild: null,
    getContext: function () { return null; }, animate: function () { return { finished: Promise.resolve() }; },
    cloneNode: function () { return __mkEl(); }, contains: function () { return false; }, matches: function () { return false; },
  };
  return el;
}
var document = {
  getElementById: function (id) { return __els[id] || (__els[id] = __mkEl(id)); },
  querySelector: function (q) { return __els["q:" + q] || (__els["q:" + q] = __mkEl()); }, querySelectorAll: function () { return []; },
  createElement: function () { return __mkEl(); }, createElementNS: function () { return __mkEl(); },
  createTextNode: function () { return __mkEl(); }, createDocumentFragment: function () { return __mkEl(); },
  addEventListener: function () {}, removeEventListener: function () {},
  documentElement: __mkEl("html"), body: __mkEl("body"), head: __mkEl("head"),
  visibilityState: "visible", title: "", cookie: "", referrer: "",
};
var __store = {};
this.localStorage = { getItem: function (k) { return k in __store ? __store[k] : null; },
                     setItem: function (k, v) { __store[k] = String(v); }, removeItem: function (k) { delete __store[k]; },
                     clear: function () { __store = {}; } };
var sessionStorage = { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} };
var location = { search: "", pathname: "/", hash: "", href: "https://wandergrade.com/", origin: "https://wandergrade.com",
                 hostname: "wandergrade.com", protocol: "https:", replace: function () {}, assign: function () {}, reload: function () {} };
var history = { replaceState: function () {}, pushState: function () {}, state: null };
var navigator = { userAgent: "jsc", language: "en-US", languages: ["en-US"], clipboard: {}, share: null, onLine: true };
function URLSearchParams(s) { var o = {}, ks = []; (s || "").replace(/^\?/, "").split("&").forEach(function (kv) {
  if (!kv) return; var i = kv.indexOf("="), k = decodeURIComponent(i < 0 ? kv : kv.slice(0, i));
  if (!(k in o)) { o[k] = i < 0 ? "" : decodeURIComponent(kv.slice(i + 1)); ks.push(k); } });
  this.get = function (k) { return k in o ? o[k] : null; }; this.has = function (k) { return k in o; };
  this.set = function (k, v) { if (!(k in o)) ks.push(k); o[k] = String(v); }; this.delete = function (k) { delete o[k]; ks = ks.filter(function (x) { return x !== k; }); };
  this.keys = function () { return ks.slice()[Symbol.iterator](); }; this.toString = function () { return ks.map(function (k) { return k + "=" + o[k]; }).join("&"); };
  this.forEach = function (f) { ks.forEach(function (k) { f(o[k], k); }); }; }
var window = this;
window.matchMedia = function () { return { matches: false, addEventListener: function () {}, addListener: function () {} }; };
window.addEventListener = function () {}; window.removeEventListener = function () {};
window.innerWidth = 1280; window.innerHeight = 800; window.devicePixelRatio = 1; window.scrollY = 0;
window.requestAnimationFrame = function () { return 0; }; window.cancelAnimationFrame = function () {};
window.getComputedStyle = function () { return { getPropertyValue: function () { return ""; } }; };
window.scrollTo = function () {};
function setTimeout(f) { return 0; } function clearTimeout() {} function setInterval() { return 0; } function clearInterval() {}
function requestIdleCallback() { return 0; }
function fetch() { return new Promise(function () {}); }   // never answers: the test sets the data itself
function MutationObserver() { this.observe = function () {}; this.disconnect = function () {}; }
function IntersectionObserver() { this.observe = function () {}; this.disconnect = function () {}; this.unobserve = function () {}; }
function ResizeObserver() { this.observe = function () {}; this.disconnect = function () {}; }
function PerformanceObserver() { this.observe = function () {}; }
function Image() { return __mkEl(); }
function Event() {} function CustomEvent() {}
var performance = { now: function () { return 0; } };
var console = { log: function () {}, warn: function () {}, error: function () {}, info: function () {} };
var Intl = this.Intl;
// A jsc built without ICU locale data (Ubuntu's libjavascriptcoregtk) groups no
// digits: (1527).toLocaleString() is "1527" there and "1,527" in the browsers
// the page runs in (and macOS's jsc). Give it en-US's.
(function () {
  if ((1527).toLocaleString() === "1,527") return;
  Number.prototype.toLocaleString = function () {
    var n = +this, neg = n < 0, p = String(Math.round(Math.abs(n) * 1000) / 1000).split(".");
    p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (neg ? "-" : "") + p.join(".");
  };
})();
