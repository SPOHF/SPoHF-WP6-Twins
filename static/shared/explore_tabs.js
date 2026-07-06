
    (function() {
        var root = document.querySelector('.explore-tabs');
        if (!root) return;
        var buttons = root.querySelectorAll('[data-tab]');
        var panels = root.querySelectorAll('[data-tab-panel]');
        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                var id = btn.dataset.tab;
                buttons.forEach(function(b) {
                    b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
                });
                panels.forEach(function(p) {
                    p.hidden = p.dataset.tabPanel !== id;
                });
                var url = new URL(window.location.href);
                url.searchParams.set('tab', id);
                history.replaceState(null, '', url.toString());
            });
        });
    })();
