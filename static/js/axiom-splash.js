window.AxiomSplash = (function () {
  var COLD_MS = 5200;
  var WARM_MS = 1200;
  var FAILSAFE_MS = 15000;

  var el = document.getElementById('axiom-splash');
  if (!el) { return { dismiss: function () {} }; }

  var reduced = window.matchMedia &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var warm = false;
  try {
    warm = sessionStorage.getItem('axiom.splash.seen') === '1';
    sessionStorage.setItem('axiom.splash.seen', '1');
  } catch (e) {
    warm = false;
  }

  if (warm || reduced) { el.classList.add('ax-warm'); }

  var minMs = (warm || reduced) ? WARM_MS : COLD_MS;
  var started = Date.now();
  var done = false;

  function remove() {
    if (!el || !el.parentNode) { return; }
    el.classList.add('ax-out');
    window.setTimeout(function () {
      if (el.parentNode) { el.parentNode.removeChild(el); }
    }, 650);
  }

  function dismiss() {
    if (done) { return; }
    done = true;
    var elapsed = Date.now() - started;
    var wait = Math.max(0, minMs - elapsed);
    window.setTimeout(remove, wait);
  }

  window.setTimeout(dismiss, FAILSAFE_MS);

  return { dismiss: dismiss };
})();
