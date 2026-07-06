
(function() {
    var dashboardId = document.documentElement.dataset.dashboard;
    var STORAGE_KEY = 'wp6-dashboard-' + dashboardId;
    var grid = document.getElementById('dashboard-grid');
    var emptyMsg = document.getElementById('dashboard-empty');

    function load() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return { version: 1, charts: [] };
            var data = JSON.parse(raw);
            return data && data.charts ? data : { version: 1, charts: [] };
        } catch (e) {
            return { version: 1, charts: [] };
        }
    }

    function save(data) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); }
        catch (e) { alert('Could not save dashboard: storage may be full.'); }
    }

    function resolveDate(chart) {
        if (chart.dateMode === 'relative') {
            var end = new Date();
            var start = new Date();
            start.setDate(start.getDate() - (chart.relativeDays || 7));
            return {
                start: start.toISOString().slice(0, 10),
                end: end.toISOString().slice(0, 10)
            };
        }
        return { start: chart.start, end: chart.end };
    }

    function buildChartUrl(chart) {
        var dates = resolveDate(chart);
        var params = new URLSearchParams();
        if (chart.s) params.set('s', chart.s);
        if (chart.r) params.set('r', chart.r);
        params.set('start', dates.start);
        params.set('end', dates.end);
        ['lbl', 'ct', 'agg', 'bkt', 'band',
         'split', 'lbl_r', 'ct_r', 'agg_r', 'bkt_r', 'band_r',
         'ideal_lo', 'ideal_hi'].forEach(function(k) {
            if (chart[k]) params.set(k, chart[k]);
        });
        return '/chart?' + params.toString();
    }

    function renderCard(chart) {
        var article = document.createElement('article');
        article.className = 'dashboard-card';
        article.dataset.chartId = chart.id;

        var dates = resolveDate(chart);
        var dateLabel = chart.dateMode === 'relative'
            ? 'Last ' + chart.relativeDays + ' days'
            : dates.start + ' to ' + dates.end;

        article.innerHTML =
            '<div class="card-actions">' +
                '<button class="delete-btn outline secondary"' +
                ' title="Remove from dashboard">&times;</button>' +
            '</div>' +
            '<h4 class="card-title" title="Click to rename">' + escapeHtml(chart.title) + '</h4>' +
            '<small>' + dateLabel + '</small>' +
            '<div class="mini-chart"><progress></progress></div>' +
            '<a href="' + buildChartUrl(chart) + '" class="card-link">Open in chart &rarr;</a>';

        article.querySelector('.delete-btn').addEventListener('click', function() {
            deleteChart(chart.id);
            article.remove();
            var data = load();
            if (data.charts.length === 0) emptyMsg.style.display = 'block';
        });

        var titleEl = article.querySelector('.card-title');
        titleEl.addEventListener('click', function() {
            var input = document.createElement('input');
            input.type = 'text';
            input.value = chart.title;
            input.className = 'rename-input';
            titleEl.replaceWith(input);
            input.focus();
            input.select();
            function finishRename() {
                var newTitle = input.value.trim() || chart.title;
                renameChart(chart.id, newTitle);
                var newH4 = document.createElement('h4');
                newH4.className = 'card-title';
                newH4.title = 'Click to rename';
                newH4.textContent = newTitle;
                input.replaceWith(newH4);
                newH4.addEventListener('click', titleEl.onclick);
                titleEl = newH4;
            }
            input.addEventListener('blur', finishRename);
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
                if (e.key === 'Escape') { input.value = chart.title; input.blur(); }
            });
        });

        return article;
    }

    function loadMiniChart(chart, divElement) {
        var dates = resolveDate(chart);
        var allKeys = [];
        if (chart.s) chart.s.split(',').forEach(function(k) {
            allKeys.push({key: k, axis: 'left'});
        });
        if (chart.r) chart.r.split(',').forEach(function(k) {
            allKeys.push({key: k, axis: 'right'});
        });

        var promises = allKeys.map(function(item) {
            var parts = item.key.split(':');
            var url = '/api/series?device=' + encodeURIComponent(parts[0]) +
                '&sensor=' + encodeURIComponent(parts.slice(1).join(':')) +
                '&start=' + dates.start + '&end=' + dates.end;
            return fetch(url)
                .then(function(r) { return r.json(); })
                .then(function(json) {
                    return {key: item.key, axis: item.axis,
                        data: json.data || []};
                })
                .catch(function() {
                    return {key: item.key, axis: item.axis, data: []};
                });
        });

        Promise.all(promises).then(function(results) {
            var traces = results.map(function(r) {
                var trace = {
                    x: r.data.map(function(d) { return d.time; }),
                    y: r.data.map(function(d) { return d.value; }),
                    name: r.key,
                    mode: 'lines',
                    yaxis: r.axis === 'right' ? 'y2' : 'y'
                };
                if (r.axis === 'right') trace.line = { dash: 'dash' };
                return trace;
            });
            var hasRight = results.some(function(r) { return r.axis === 'right'; });
            var layout = {
                height: 250,
                margin: { t: 10, b: 30, l: 40, r: hasRight ? 40 : 10 },
                showlegend: false,
                xaxis: { type: 'date' },
                yaxis: {},
                yaxis2: { overlaying: 'y', side: 'right', showgrid: false },
                template: 'plotly_white',
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)'
            };
            divElement.innerHTML = '';
            if (traces.every(function(t) { return t.x.length === 0; })) {
                divElement.innerHTML =
                    '<p style="text-align:center;' +
                    'color:var(--pico-muted-color)">' +
                    'No data available</p>';
                return;
            }
            Plotly.newPlot(divElement, traces, layout, { displayModeBar: false, responsive: true });
        });
    }

    function deleteChart(id) {
        var data = load();
        data.charts = data.charts.filter(function(c) { return c.id !== id; });
        save(data);
    }

    function renameChart(id, newTitle) {
        var data = load();
        data.charts.forEach(function(c) { if (c.id === id) c.title = newTitle; });
        save(data);
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    var data = load();
    if (data.charts.length === 0) {
        emptyMsg.style.display = 'block';
        return;
    }
    emptyMsg.style.display = 'none';
    data.charts.forEach(function(chart) {
        var card = renderCard(chart);
        grid.appendChild(card);
        loadMiniChart(chart, card.querySelector('.mini-chart'));
    });
})();
