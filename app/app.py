"""Dash application factory — no external stylesheets, no dash-bootstrap-components.

Cloned from Decompose (which cloned Spin Rate). The panel is warmed here at import so
the one-time generation happens at process boot, never on a visitor's first request.
"""

import os
import secrets

import dash

from app import panel_data

app = dash.Dash(
    __name__,
    assets_folder="../assets",
    suppress_callback_exceptions=True,
    title="Leaky Bucket — Trial vs Repeat",
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": "Of the households that tried you, how many came back, and is penetration growth real adoption or expensive sampling?"},
        {"property": "og:title", "content": "Leaky Bucket: Trial vs Repeat"},
        {"property": "og:description", "content": "Of the households that tried you, how many came back, and is penetration growth real adoption or expensive sampling?"},
        {"property": "og:type", "content": "website"},
        {"property": "og:url", "content": "https://leakybucket.lailarallc.com/"},
        {"property": "og:image", "content": "https://lailarallc.com/og/s/leakybucket.png"},
        {"property": "og:image:secure_url", "content": "https://lailarallc.com/og/s/leakybucket.png"},
        {"property": "og:image:type", "content": "image/png"},
        {"property": "og:image:width", "content": "1200"},
        {"property": "og:image:height", "content": "630"},
        {"property": "og:image:alt", "content": "Leaky Bucket: Trial vs Repeat"},
        {"name": "twitter:card", "content": "summary_large_image"},
        {"name": "twitter:image", "content": "https://lailarallc.com/og/s/leakybucket.png"},
    ],
)
server = app.server
server.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# Build the in-process panel once, at startup (see panel_data.warm_cache).
panel_data.warm_cache()

# ── Branded loading overlay ──────────────────────────────────────────
# Leaky Bucket is sent to prospects as a cold link, so the first hydration (Dash
# renderer boot + the default view's data callback) leaves a blank screen for a beat.
# That reads as broken. This overlay is plain static HTML/CSS injected into the page
# body, painted on the first frame before any Dash JS runs; an inline script fades it
# out the moment the default chart has drawn. Colours/fonts are literal Lailara tokens
# so the overlay is styled even before the external stylesheet loads.
_LOADING_OVERLAY = """
    <style>
      #lb-loading {
        position: fixed;
        inset: 0;
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #f5f3ee; /* Canvas — London-100 warmed */
        transition: opacity 300ms ease-out;
      }
      #lb-loading.lb-hide { opacity: 0; pointer-events: none; }
      .lb-load-inner { text-align: center; padding: 0 24px; }
      .lb-load-spinner {
        width: 46px;
        height: 46px;
        margin: 0 auto 26px;
        border: 3px solid #d9d9d9;     /* London-85 gridline */
        border-top-color: #1f2e7a;     /* Chicago-20 navy */
        border-radius: 50%;
        animation: lb-spin 900ms linear infinite;
      }
      .lb-load-brand {
        font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
        font-size: 26px;              /* DS Brand-name step; 20px mobile below */
        font-weight: 700;
        color: #0d0d0d;                /* Ink */
        letter-spacing: -0.01em;
        line-height: 1.2;
      }
      .lb-load-sub {
        font-family: 'Source Sans 3', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 12px;
        font-weight: 600;
        color: #595959;                /* Text secondary */
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-top: 10px;
      }
      .lb-load-hint {
        font-family: 'Source Sans 3', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 14px;
        font-weight: 400;
        color: #595959;                /* Text secondary */
        margin-top: 22px;
      }
      @keyframes lb-spin { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) {
        #lb-loading { transition: none; }
        .lb-load-spinner { animation: none; border-color: #1f2e7a; }
      }
      @media (max-width: 640px) {
        .lb-load-brand { font-size: 20px; }
      }
    </style>
    <div id="lb-loading" role="status" aria-live="polite" aria-label="Loading Leaky Bucket">
      <div class="lb-load-inner">
        <div class="lb-load-spinner" aria-hidden="true"></div>
        <div class="lb-load-brand">Leaky Bucket</div>
        <div class="lb-load-sub">Trial &times; Repeat</div>
        <div class="lb-load-hint">Measuring who came back&hellip;</div>
      </div>
    </div>
    <script>
      (function () {
        var SAFETY_MS = 20000;
        function hide() {
          var el = document.getElementById('lb-loading');
          if (!el || el.classList.contains('lb-hide')) return;
          el.classList.add('lb-hide');
          setTimeout(function () {
            if (el && el.parentNode) el.parentNode.removeChild(el);
          }, 400);
        }
        // The default tab is interactive once Plotly has drawn the verdict chart (its
        // data callback has returned). If it never paints, SAFETY_MS hides the overlay
        // anyway, so the visitor is never trapped.
        function ready() {
          return !!document.querySelector('#verdict-chart .js-plotly-plot');
        }
        function check() {
          if (ready()) { hide(); return true; }
          return false;
        }
        if (check()) return;
        var obs = new MutationObserver(function () {
          if (check()) obs.disconnect();
        });
        obs.observe(document.documentElement, { childList: true, subtree: true });
        setTimeout(function () { obs.disconnect(); hide(); }, SAFETY_MS);
      })();
    </script>
"""

app.index_string = """<!DOCTYPE html>
<html lang="en">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        __LOADING_OVERLAY__
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>""".replace("__LOADING_OVERLAY__", _LOADING_OVERLAY)
