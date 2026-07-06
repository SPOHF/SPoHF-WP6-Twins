
(function() {
    var chartDiv = document.getElementById('chart-area');
    var panelDiv = document.getElementById('sensor-panel');
    var statsDiv = document.getElementById('chart-stats');
    var toggleBtn = document.getElementById('panel-toggle');
    if (!chartDiv || !panelDiv) return;

    // State: map of "device:sensor" -> {axis: "left"|"right", traceIdx: number}
    var activeSeries = {};
    var seriesData = {};  // key -> {times: [], values: []}
    var totalPoints = 0;
    var BUCKET_STEPS = [0, 1, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 10080, 20160, 43200];

    var splitMode = false;
    var idealLo = null;
    var idealHi = null;
    function defaultAxisCfg() {
        return {
            labelFormat: 'smart',
            chartType: 'line',
            aggregateEnabled: false,
            aggregateFunc: 'avg',
            bucketMinutes: 10,
            bandEnabled: false
        };
    }
    var axisCfg = { left: defaultAxisCfg(), right: defaultAxisCfg() };
    function cfgFor(axis) { return splitMode ? axisCfg[axis] : axisCfg.left; }

    // Parse URL params
    var params = new URLSearchParams(window.location.search);
    var leftSpecs = (params.get('s') || '').split(',').filter(Boolean);
    var rightSpecs = (params.get('r') || '').split(',').filter(Boolean);
    var startDate = params.get('start') || '';
    var endDate = params.get('end') || '';

    function readLabelFormat(name, fallback) {
        var v = params.get(name) || '';
        return ['smart', 'short', 'raw'].indexOf(v) !== -1 ? v : fallback;
    }
    function readChartType(name, fallback) {
        var v = params.get(name) || '';
        return ['line', 'scatter', 'box'].indexOf(v) !== -1 ? v : fallback;
    }
    function readAggInto(cfg, aggName, bktName, bandName) {
        var agg = params.get(aggName);
        if (agg === 'off') {
            cfg.aggregateEnabled = false;
        } else if (agg && ['avg', 'max', 'min', 'sum'].indexOf(agg) !== -1) {
            cfg.aggregateEnabled = true;
            cfg.aggregateFunc = agg;
        }
        var bkt = parseInt(params.get(bktName));
        if (!isNaN(bkt) && BUCKET_STEPS.indexOf(bkt) !== -1) {
            cfg.bucketMinutes = bkt;
        }
        var band = params.get(bandName);
        if (band === '1') cfg.bandEnabled = true;
        else if (band === '0') cfg.bandEnabled = false;
    }
    axisCfg.left.labelFormat = readLabelFormat('lbl', 'smart');
    axisCfg.left.chartType = readChartType('ct', 'line');
    readAggInto(axisCfg.left, 'agg', 'bkt', 'band');
    var _idealLoRaw = parseFloat(params.get('ideal_lo'));
    var _idealHiRaw = parseFloat(params.get('ideal_hi'));
    if (Number.isFinite(_idealLoRaw)) idealLo = _idealLoRaw;
    if (Number.isFinite(_idealHiRaw)) idealHi = _idealHiRaw;
    if (params.get('split') === '1') {
        splitMode = true;
        // Right-axis values fall back to left for any param not explicitly set
        axisCfg.right.labelFormat = readLabelFormat('lbl_r', axisCfg.left.labelFormat);
        axisCfg.right.chartType = readChartType('ct_r', axisCfg.left.chartType);
        axisCfg.right.aggregateEnabled = axisCfg.left.aggregateEnabled;
        axisCfg.right.aggregateFunc = axisCfg.left.aggregateFunc;
        axisCfg.right.bucketMinutes = axisCfg.left.bucketMinutes;
        axisCfg.right.bandEnabled = axisCfg.left.bandEnabled;
        readAggInto(axisCfg.right, 'agg_r', 'bkt_r', 'band_r');
    }

    // Build initial active set from URL
    var initialLeft = {};
    var initialRight = {};
    leftSpecs.forEach(function(s) { initialLeft[s] = true; });
    rightSpecs.forEach(function(s) { initialRight[s] = true; });

    // Initialize empty Plotly chart
    var layout = {
        template: 'plotly_white',
        hovermode: 'x unified',
        height: 600,
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        yaxis2: {overlaying: 'y', side: 'right', showgrid: false},
        boxmode: 'group'
    };
    Plotly.newPlot(chartDiv, [], layout, {responsive: true});

    // Toggle panel
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            var sp = document.querySelector('.sensor-panel');
            sp.classList.toggle('collapsed');
            toggleBtn.textContent = sp.classList.contains('collapsed')
                ? 'Show controls' : 'Hide controls';
            Plotly.Plots.resize(chartDiv);
        });
    }

    // Clear all selections
    var clearBtn = document.getElementById('clear-all');
    if (clearBtn) {
        clearBtn.addEventListener('click', function(e) {
            e.preventDefault();
            // Remove all traces from chart
            var keys = Object.keys(activeSeries);
            if (keys.length === 0) return;
            var indices = keys.map(function(k) {
                return activeSeries[k].traceIdx;
            }).sort(function(a, b) { return b - a; });
            Plotly.deleteTraces(chartDiv, indices);
            activeSeries = {};
            seriesData = {};
            totalPoints = 0;
            // Uncheck all checkboxes
            var cbs = panelDiv.querySelectorAll(
                'input[type="checkbox"]:checked');
            cbs.forEach(function(cb) { cb.checked = false; });
            panelDiv.querySelectorAll('.sensor-item').forEach(
                function(el) { el.classList.remove('active'); });
            showEmpty(true);
            syncUrl();
            updateStats();
            updateY2();
            updateAllBadges();
        });
    }

    // Fetch sensor list (nested by device) and flatten for internal use
    var allSensors = [];
    var currentGrouping = 'measurement';
    fetch('/api/sensors')
        .then(function(r) { return r.json(); })
        .then(function(nested) {
            allSensors = [];
            nested.forEach(function(d) {
                var dm = d.meta || {};
                d.sensors.forEach(function(s) {
                    allSensors.push({
                        device: d.device,
                        sensor: s.sensor,
                        device_meta: dm,
                        sensor_meta: s.meta || {}
                    });
                });
            });
            buildTree(allSensors, currentGrouping);
            loadInitialSeries();
        });

    // Grouping toggle
    var groupBtns = document.querySelectorAll('.group-btn');
    groupBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var mode = btn.dataset.group;
            if (mode === currentGrouping) return;
            currentGrouping = mode;
            groupBtns.forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
            buildTree(allSensors, currentGrouping);
        });
    });

    function activeAggValueFor(axis) {
        var c = axisCfg[axis];
        return c.aggregateEnabled ? c.aggregateFunc : 'off';
    }

    function refreshControlActiveStates() {
        document.querySelectorAll('.ct-btn').forEach(function(btn) {
            var axis = btn.dataset.axis;
            btn.classList.toggle('active',
                btn.dataset.ct === axisCfg[axis].chartType);
        });
        document.querySelectorAll('.label-btn').forEach(function(btn) {
            var axis = btn.dataset.axis;
            btn.classList.toggle('active',
                btn.dataset.label === axisCfg[axis].labelFormat);
        });
        document.querySelectorAll('.agg-btn').forEach(function(btn) {
            var axis = btn.dataset.axis;
            var isBox = axisCfg[axis].chartType === 'box';
            btn.classList.toggle('active',
                btn.dataset.agg === activeAggValueFor(axis));
            // Boxplots ignore the aggregate func — only the slider matters.
            btn.disabled = isBox;
            btn.title = isBox ? 'Ignored for boxplots — the slider sets box width' : '';
        });
        document.querySelectorAll('.bucket-slider-input').forEach(function(slider) {
            var axis = slider.dataset.axis;
            var c = axisCfg[axis];
            var isBox = c.chartType === 'box';
            var idx = BUCKET_STEPS.indexOf(c.bucketMinutes);
            if (idx < 0) idx = 3;
            slider.value = idx;
            // Box keeps the slider live (it sets box width); otherwise the
            // slider only applies when aggregation is on.
            slider.disabled = isBox ? false : !c.aggregateEnabled;
            var labelEl = slider.parentElement.querySelector(
                '.bucket-label[data-axis="' + axis + '"]');
            if (labelEl) labelEl.textContent = formatBucket(c.bucketMinutes);
            var prefixEl = slider.parentElement.querySelector(
                '.bucket-prefix[data-axis="' + axis + '"]');
            if (prefixEl) prefixEl.textContent = isBox ? 'Box width:' : 'Bucket:';
        });
        document.querySelectorAll('.band-input').forEach(function(box) {
            var c = axisCfg[box.dataset.axis];
            // The range band is a line concept; a box already shows spread.
            var applies = bandAppliesTo(c) && c.chartType !== 'box';
            box.checked = c.bandEnabled;
            box.disabled = !applies;
            var label = box.closest('.band-toggle');
            if (label) label.classList.toggle('disabled', !applies);
        });
    }

    function wireAxisControls(rootEl) {
        rootEl.querySelectorAll('.ct-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var axis = btn.dataset.axis;
                var ct = btn.dataset.ct;
                if (ct === axisCfg[axis].chartType) return;
                var wasBox = axisCfg[axis].chartType === 'box';
                axisCfg[axis].chartType = ct;
                refreshControlActiveStates();
                // Box fetches raw while non-box-with-agg fetches bucketed, so
                // crossing the box boundary changes the data shape and needs a
                // refetch. line<->scatter share the same data — re-render only.
                if (wasBox !== (ct === 'box')) {
                    refetchAll();
                } else {
                    rebuildTraces();
                    syncUrl();
                }
            });
        });
        rootEl.querySelectorAll('.label-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var axis = btn.dataset.axis;
                var fmt = btn.dataset.label;
                if (fmt === axisCfg[axis].labelFormat) return;
                axisCfg[axis].labelFormat = fmt;
                refreshControlActiveStates();
                relabelAllTraces();
                syncUrl();
            });
        });
        rootEl.querySelectorAll('.agg-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var axis = btn.dataset.axis;
                var fn = btn.dataset.agg;
                if (fn === activeAggValueFor(axis)) return;
                if (fn === 'off') {
                    axisCfg[axis].aggregateEnabled = false;
                } else {
                    axisCfg[axis].aggregateEnabled = true;
                    axisCfg[axis].aggregateFunc = fn;
                }
                refreshControlActiveStates();
                refetchAll();
            });
        });
        rootEl.querySelectorAll('.bucket-slider-input').forEach(function(slider) {
            slider.addEventListener('input', function() {
                var axis = slider.dataset.axis;
                var minutes = BUCKET_STEPS[parseInt(slider.value)];
                var labelEl = slider.parentElement.querySelector(
                    '.bucket-label[data-axis="' + axis + '"]');
                if (labelEl) labelEl.textContent = formatBucket(minutes);
            });
            slider.addEventListener('change', function() {
                var axis = slider.dataset.axis;
                axisCfg[axis].bucketMinutes = BUCKET_STEPS[parseInt(slider.value)];
                if (axisCfg[axis].chartType === 'box') {
                    // Box width is a pure client-side regroup of raw points.
                    rebuildTraces();
                    syncUrl();
                } else if (axisCfg[axis].aggregateEnabled) {
                    refetchAll();
                }
            });
        });
        rootEl.querySelectorAll('.band-input').forEach(function(box) {
            box.addEventListener('change', function() {
                var axis = box.dataset.axis;
                axisCfg[axis].bandEnabled = box.checked;
                // min/max are already on the client whenever aggregation is
                // on, so toggling the band is a pure re-render — no refetch.
                rebuildTraces();
                syncUrl();
            });
        });
    }

    var unifiedBlock = document.getElementById('axis-controls-unified');
    var splitBlock = document.getElementById('axis-controls-split');
    if (unifiedBlock) wireAxisControls(unifiedBlock);
    if (splitBlock) wireAxisControls(splitBlock);

    function applySplitVisibility() {
        if (unifiedBlock) unifiedBlock.style.display = splitMode ? 'none' : '';
        if (splitBlock)   splitBlock.style.display   = splitMode ? '' : 'none';
    }

    function axisPresence() {
        var hasLeft = false;
        var hasRight = false;
        Object.keys(activeSeries).forEach(function(k) {
            if (activeSeries[k].axis === 'right') hasRight = true;
            else hasLeft = true;
        });
        return { hasLeft: hasLeft, hasRight: hasRight };
    }

    function hasDualAxesActive() {
        var presence = axisPresence();
        return presence.hasLeft && presence.hasRight;
    }

    function idealRangeAxisRef() {
        var presence = axisPresence();
        return presence.hasRight && !presence.hasLeft ? 'y2' : 'y';
    }

    function applyIdealRangeAvailability() {
        var disableIdeal = hasDualAxesActive();
        var idealSection = document.getElementById('ideal-range-section');
        if (idealSection) {
            idealSection.classList.toggle('disabled', disableIdeal);
            idealSection.querySelectorAll('input').forEach(function(inp) {
                inp.disabled = disableIdeal;
            });
        }
    }

    var splitToggle = document.getElementById('axis-split-toggle');
    if (splitToggle) {
        splitToggle.checked = splitMode;
        applySplitVisibility();
        applyIdealRangeAvailability();
        splitToggle.addEventListener('change', function() {
            if (splitToggle.checked) {
                axisCfg.right = JSON.parse(JSON.stringify(axisCfg.left));
                splitMode = true;
            } else {
                splitMode = false;
            }
            applySplitVisibility();
            applyIdealRangeAvailability();
            refreshControlActiveStates();
            refetchAll();
        });
    }

    // Y-Left / Y-Right tabs: show one axis's controls at a time in split mode
    // so the panel stays compact. Pure UI state — every control stays wired and
    // in the DOM whether or not its panel is visible.
    var axisTabs = document.querySelectorAll('.axis-tab');
    var axisPanels = document.querySelectorAll('.axis-tab-panel');
    axisTabs.forEach(function(tab) {
        tab.addEventListener('click', function() {
            var which = tab.dataset.axistab;
            axisTabs.forEach(function(t) {
                t.classList.toggle('active', t === tab);
            });
            axisPanels.forEach(function(p) {
                p.hidden = p.dataset.axispanel !== which;
            });
        });
    });

    refreshControlActiveStates();

    // --- Ideal range inputs ---
    var idealLoInput = document.getElementById('ideal-lo');
    var idealHiInput = document.getElementById('ideal-hi');
    if (idealLoInput && idealLo !== null) idealLoInput.value = idealLo;
    if (idealHiInput && idealHi !== null) idealHiInput.value = idealHi;
    function onIdealChange() {
        var v;
        if (idealLoInput) {
            v = parseFloat(idealLoInput.value);
            idealLo = Number.isFinite(v) ? v : null;
        }
        if (idealHiInput) {
            v = parseFloat(idealHiInput.value);
            idealHi = Number.isFinite(v) ? v : null;
        }
        updateIdealRange();
        syncUrl();
    }
    if (idealLoInput) idealLoInput.addEventListener('change', onIdealChange);
    if (idealHiInput) idealHiInput.addEventListener('change', onIdealChange);

    function buildTree(sensors, groupBy) {
        // Group sensors into {groupKey: [{device, sensor, ...}, ...]}
        var groups = {};
        sensors.forEach(function(s) {
            var key;
            if (groupBy === 'device') key = s.device;
            else if (groupBy === 'position')
                key = (s.device_meta && s.device_meta.position) || 'Ungrouped';
            else key = (s.sensor_meta && s.sensor_meta.type) || s.sensor;
            if (!groups[key]) groups[key] = [];
            groups[key].push(s);
        });

        // Build current checked state from activeSeries
        var checkedLeft = {};
        var checkedRight = {};
        Object.keys(activeSeries).forEach(function(k) {
            if (activeSeries[k].axis === 'right') checkedRight[k] = true;
            else checkedLeft[k] = true;
        });
        // On first load, also use URL state
        if (Object.keys(activeSeries).length === 0) {
            checkedLeft = initialLeft;
            checkedRight = initialRight;
        }

        var html = '';
        var sortedKeys = Object.keys(groups).sort();
        sortedKeys.forEach(function(groupKey) {
            var items = groups[groupKey];
            var open = items.some(function(s) {
                var key = s.device + ':' + s.sensor;
                return checkedLeft[key] || checkedRight[key];
            });
            html += '<details class="sensor-group"'
                + (open ? ' open' : '') + '>';
            html += '<summary>' + groupKey
                + ' <small>(' + items.length + ')</small>'
                + '<span class="group-badge"></span>'
                + '</summary>';
            items.forEach(function(s) {
                var key = s.device + ':' + s.sensor;
                var sm = s.sensor_meta || {};
                var dm = s.device_meta || {};
                // Display label: use alias if available
                var label;
                if (groupBy === 'device') label = sm.alias || s.sensor;
                else if (groupBy === 'position') label = (sm.alias || s.sensor) + ' — ' + s.device;
                else label = s.device + ' — ' + (sm.alias || s.sensor);
                // Unit badge
                var unitBadge = sm.unit
                    ? ' <span class="unit-badge">' + sm.unit + '</span>'
                    : '';
                // Tooltip with metadata
                var tipParts = [key];
                if (dm.description) tipParts.push(dm.description);
                if (dm.position) tipParts.push('Position: ' + dm.position);
                if (sm.intention) tipParts.push(sm.intention);
                if (dm.type) tipParts.push('Type: ' + dm.type);
                var tip = tipParts.join(' | ');
                var isLeft = !!checkedLeft[key];
                var isRight = !!checkedRight[key];
                var activeClass = (isLeft || isRight)
                    ? ' active' : '';
                html += '<div class="sensor-item' + activeClass
                    + '" data-key="' + key + '">';
                html += '<label class="cb-label" title="Left Y">'
                    + '<input type="checkbox" data-axis="left"'
                    + ' data-key="' + key + '"'
                    + (isLeft ? ' checked' : '')
                    + '> L</label>';
                html += '<label class="cb-label" title="Right Y">'
                    + '<input type="checkbox" data-axis="right"'
                    + ' data-key="' + key + '"'
                    + (isRight ? ' checked' : '')
                    + '> R</label>';
                html += '<span class="device-name" title="'
                    + tip + '">' + label + unitBadge + '</span>';
                html += '</div>';
            });
            html += '</details>';
        });
        panelDiv.innerHTML = html;
        updateAllBadges();
    }

    // Listen for changes (once, outside buildTree to avoid stacking)
    panelDiv.addEventListener('change', function(e) {
        var cb = e.target;
        if (cb.type !== 'checkbox') return;
        var key = cb.dataset.key;
        var axis = cb.dataset.axis;
        var otherAxis = axis === 'left' ? 'right' : 'left';
        var item = panelDiv.querySelector(
            '[data-key="' + key + '"]');

        if (cb.checked) {
            // Uncheck the other axis for this sensor
            var other = item.querySelector(
                'input[data-axis="' + otherAxis + '"]');
            if (other && other.checked) {
                other.checked = false;
            }
            addOrUpdateSeries(key, axis);
            if (item) item.classList.add('active');
        } else {
            removeSeries(key);
            // Check if any checkbox still checked
            var any = item.querySelector(
                'input[type="checkbox"]:checked');
            if (!any && item) {
                item.classList.remove('active');
            }
            // Sync immediately for removals (synchronous)
            syncUrl();
            updateStats();
            updateY2();
        }
        updateAllBadges();
    });

    // Clicking name toggles the L checkbox (once, outside buildTree)
    panelDiv.addEventListener('click', function(e) {
        var name = e.target.closest('.device-name');
        if (!name) return;
        var item = name.closest('.sensor-item');
        if (!item) return;
        var lcb = item.querySelector(
            'input[data-axis="left"]');
        if (lcb) {
            lcb.checked = !lcb.checked;
            lcb.dispatchEvent(
                new Event('change', {bubbles: true}));
        }
    });

    function updateAllBadges() {
        var groups = panelDiv.querySelectorAll('.sensor-group');
        groups.forEach(function(g) {
            var checked = g.querySelectorAll(
                'input[type="checkbox"]:checked');
            var badge = g.querySelector('.group-badge');
            if (badge) {
                badge.textContent = checked.length > 0
                    ? ' [' + checked.length + ']' : '';
            }
        });
    }

    function loadInitialSeries() {
        var allSpecs = leftSpecs.map(function(s) {
            return {key: s, axis: 'left'};
        }).concat(rightSpecs.map(function(s) {
            return {key: s, axis: 'right'};
        }));
        if (allSpecs.length === 0) {
            showEmpty(true);
            return;
        }
        showEmpty(false);
        var loaded = 0;
        allSpecs.forEach(function(spec) {
            fetchAndAdd(spec.key, spec.axis, function() {
                loaded++;
                if (loaded === allSpecs.length) {
                    rebuildTraces();
                    updateStats();
                    updateY2();
                }
            });
        });
    }

    function sensorLabel(key, axis) {
        var s = allSensors.find(function(s) {
            return s.device + ':' + s.sensor === key;
        });
        if (!s) return key;
        var sm = s.sensor_meta || {};
        var dm = s.device_meta || {};
        var alias = sm.alias || s.sensor;
        var fmt = cfgFor(axis).labelFormat;

        if (fmt === 'raw') {
            return s.device + ' | ' + s.sensor;
        }
        var pos = dm.position || s.device;
        if (fmt === 'short') {
            return pos + ' — ' + alias;
        }
        // 'smart': position + alias + intention snippet
        var label = pos + ' — ' + alias;
        if (sm.intention) {
            var snippet = sm.intention.split(',')[0];
            if (snippet.length > 30) snippet = snippet.substring(0, 30) + '…';
            label += ' (' + snippet + ')';
        }
        return label;
    }

    function anyAggregateEnabled() {
        return cfgFor('left').aggregateEnabled || cfgFor('right').aggregateEnabled;
    }

    function relabelAllTraces() {
        if (anyAggregateEnabled()) { rebuildTraces(); return; }
        var keys = Object.keys(activeSeries);
        if (keys.length === 0) return;
        keys.forEach(function(k) {
            var idx = activeSeries[k].traceIdx;
            var axis = activeSeries[k].axis;
            Plotly.restyle(chartDiv, { name: sensorLabel(k, axis) }, [idx]);
        });
    }

    // Colors are assigned by sorted-key index: unique within a chart, and
    // stable per key as long as the active-series set is unchanged.
    var TRACE_COLORS = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
        '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
        '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
        '#c49c94', '#f7b6d2', '#c7c7c7', '#dbdb8d', '#9edae5'
    ];
    function buildColorMap() {
        var sorted = Object.keys(activeSeries).slice().sort();
        var m = {};
        sorted.forEach(function(k, i) {
            m[k] = TRACE_COLORS[i % TRACE_COLORS.length];
        });
        return m;
    }

    // Translucent fill for the range band, derived from the series' own
    // palette colour (all TRACE_COLORS are #rrggbb).
    function hexToRgba(hex, alpha) {
        var r = parseInt(hex.slice(1, 3), 16);
        var g = parseInt(hex.slice(3, 5), 16);
        var b = parseInt(hex.slice(5, 7), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    // The band toggle is only meaningful for true ranges: it needs an active
    // aggregation, and SUM puts the line on a different scale than min/max.
    function bandAppliesTo(cfg) {
        return cfg.aggregateEnabled && cfg.aggregateFunc !== 'sum';
    }

    // Combine already-bucketed values from multiple series that share one
    // axis label. The server aligned every series to identical bucket
    // boundaries, so values at the same timestamp are directly combinable.
    // AVG must be count-weighted: a plain mean of per-series means is biased
    // when buckets hold unequal numbers of raw readings (e.g. a partial day).
    function combineAgg(values, counts, func) {
        if (values.length === 0) return null;
        if (func === 'max') return Math.max.apply(null, values);
        if (func === 'min') return Math.min.apply(null, values);
        if (func === 'sum') {
            var s = 0; values.forEach(function(v) { s += v; }); return s;
        }
        var num = 0, den = 0;  // avg, count-weighted
        for (var i = 0; i < values.length; i++) {
            num += values[i] * counts[i];
            den += counts[i];
        }
        return den > 0 ? num / den : null;
    }

    function formatBucket(mins) {
        if (mins === 0) return 'Off';
        if (mins < 60) return mins + ' min';
        if (mins === 60) return '1h';
        if (mins < 1440) {
            var h = mins / 60;
            return (mins % 60 ? h.toFixed(1) : h.toFixed(0)) + 'h';
        }
        if (mins === 1440) return '1 day';
        if (mins === 10080) return '1 week';
        if (mins === 20160) return '2 weeks';
        if (mins === 43200) return '1 month';
        return (mins / 1440) + ' days';
    }

    // Floor a local-ISO timestamp to its box-grouping bucket start. Boxes are
    // grouped entirely on the client (the server never buckets a box), so this
    // only needs to land on sensible local boundaries: sub-day widths floor
    // within the local day from midnight; day+ widths floor to whole local days.
    function floorBoxTime(iso, minutes) {
        if (!minutes || minutes <= 0) return iso;
        var m = iso.match(
            /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})([+-]\d{2}:\d{2}|Z)?/);
        if (!m) return iso;
        var Y = +m[1], Mo = +m[2], D = +m[3], H = +m[4], Mi = +m[5];
        var offset = m[7] && m[7] !== 'Z' ? m[7] : (m[7] === 'Z' ? 'Z' : '');
        function pad(n) { return (n < 10 ? '0' : '') + n; }
        if (minutes < 1440) {
            var since = H * 60 + Mi;
            var fl = Math.floor(since / minutes) * minutes;
            return Y + '-' + pad(Mo) + '-' + pad(D) + 'T'
                + pad(Math.floor(fl / 60)) + ':' + pad(fl % 60) + ':00' + offset;
        }
        var dayMs = 86400000;
        var stepDays = Math.round(minutes / 1440);
        var dayNum = Math.floor(Date.UTC(Y, Mo - 1, D) / dayMs);
        var dt = new Date(Math.floor(dayNum / stepDays) * stepDays * dayMs);
        return dt.getUTCFullYear() + '-' + pad(dt.getUTCMonth() + 1) + '-'
            + pad(dt.getUTCDate()) + 'T00:00:00' + offset;
    }

    function rebuildTraces() {
        // Clear all Plotly traces
        var traceCount = chartDiv.data ? chartDiv.data.length : 0;
        if (traceCount > 0) {
            var indices = [];
            for (var i = 0; i < traceCount; i++) indices.push(i);
            Plotly.deleteTraces(chartDiv, indices);
        }

        var keys = Object.keys(activeSeries);
        if (keys.length === 0) return;

        var colorMap = buildColorMap();

        // Partition keys by axis so each side can use its own config
        var keysByAxis = { left: [], right: [] };
        keys.forEach(function(k) {
            var axis = activeSeries[k].axis;
            keysByAxis[axis].push(k);
        });

        var traces = [];
        var traceIdxMap = {};

        ['left', 'right'].forEach(function(axis) {
            var axisKeys = keysByAxis[axis];
            if (axisKeys.length === 0) return;
            var cfg = cfgFor(axis);

            if (cfg.chartType === 'box') {
                // One box-series per sensor (no same-label pooling). Each raw
                // point is floored to its box-width bucket so Plotly groups the
                // distribution and computes the quartiles; boxmode:'group' sits
                // same-bucket sensors side-by-side on the shared time axis.
                axisKeys.forEach(function(k) {
                    var sd = seriesData[k];
                    if (!sd) return;
                    var color = colorMap[k];
                    var bx = sd.times.map(function(t) {
                        return floorBoxTime(t, cfg.bucketMinutes);
                    });
                    traceIdxMap[k] = traces.length;
                    traces.push({
                        type: 'box',
                        x: bx, y: sd.values,
                        name: sensorLabel(k, axis),
                        yaxis: axis === 'right' ? 'y2' : 'y',
                        marker: {color: color},
                        line: {color: color}
                    });
                });
                return;
            }

            // Render-mode seam: scatter draws the same points as markers.
            var traceMode = cfg.chartType === 'scatter' ? 'markers' : 'lines';

            if (!cfg.aggregateEnabled) {
                axisKeys.forEach(function(k) {
                    var sd = seriesData[k];
                    if (!sd) return;
                    var color = colorMap[k];
                    var trace = {
                        x: sd.times, y: sd.values,
                        name: sensorLabel(k, axis),
                        mode: traceMode,
                        yaxis: axis === 'right' ? 'y2' : 'y',
                        line: {color: color},
                        marker: {color: color}
                    };
                    if (axis === 'right') { trace.line.dash = 'dash'; }
                    traceIdxMap[k] = traces.length;
                    traces.push(trace);
                });
            } else {
                var groups = {};
                axisKeys.forEach(function(k) {
                    var sd = seriesData[k];
                    if (!sd) return;
                    var label = sensorLabel(k, axis);
                    if (!groups[label]) {
                        groups[label] = { label: label, series: [], firstKey: k };
                    } else if (k < groups[label].firstKey) {
                        groups[label].firstKey = k;
                    }
                    groups[label].series.push(sd);
                });
                Object.keys(groups).forEach(function(label) {
                    var g = groups[label];
                    var merged;
                    if (g.series.length === 1) {
                        // Server already bucketed+aggregated this series.
                        var s0 = g.series[0];
                        merged = {
                            times: s0.times, values: s0.values,
                            mins: s0.mins, maxs: s0.maxs
                        };
                    } else {
                        // Series share a label: recombine on the identical
                        // server-side bucket timestamps, count-weighting AVG.
                        // The band spans all series, so min-of-mins/max-of-maxs.
                        var bmap = {};
                        g.series.forEach(function(sd) {
                            sd.times.forEach(function(t, i) {
                                var v = sd.values[i];
                                if (v === null || v === undefined) return;
                                if (!bmap[t]) bmap[t] = {
                                    vals: [], counts: [], mins: [], maxs: [] };
                                bmap[t].vals.push(v);
                                bmap[t].counts.push(sd.counts ? sd.counts[i] : 1);
                                if (sd.mins && sd.mins[i] != null) bmap[t].mins.push(sd.mins[i]);
                                if (sd.maxs && sd.maxs[i] != null) bmap[t].maxs.push(sd.maxs[i]);
                            });
                        });
                        var sortedTimes = Object.keys(bmap).sort();
                        var aggValues = sortedTimes.map(function(t) {
                            return combineAgg(
                                bmap[t].vals, bmap[t].counts, cfg.aggregateFunc);
                        });
                        var aggMins = sortedTimes.map(function(t) {
                            return bmap[t].mins.length
                                ? Math.min.apply(null, bmap[t].mins) : null; });
                        var aggMaxs = sortedTimes.map(function(t) {
                            return bmap[t].maxs.length
                                ? Math.max.apply(null, bmap[t].maxs) : null; });
                        merged = {
                            times: sortedTimes, values: aggValues,
                            mins: aggMins, maxs: aggMaxs
                        };
                    }

                    var suffix = g.series.length > 1
                    ? ' [' + cfg.aggregateFunc.toUpperCase() + '×' + g.series.length + ']'
                    : '';
                var color = colorMap[g.firstKey];
                var yaxisName = axis === 'right' ? 'y2' : 'y';

                // Range band: a translucent min->max area drawn *before* the
                // line so the line sits on top. Two zero-width traces (lower
                // then upper-with-fill) make Plotly shade between them.
                var bandShown = cfg.bandEnabled && bandAppliesTo(cfg)
                    && merged.mins && merged.maxs;
                if (bandShown) {
                    traces.push({
                        x: merged.times, y: merged.mins,
                        mode: 'lines', line: {width: 0},
                        yaxis: yaxisName,
                        hoverinfo: 'skip', showlegend: false
                    });
                    traces.push({
                        x: merged.times, y: merged.maxs,
                        mode: 'lines', line: {width: 0},
                        fill: 'tonexty', fillcolor: hexToRgba(color, 0.18),
                        yaxis: yaxisName,
                        hoverinfo: 'skip', showlegend: false
                    });
                }

                var trace = {
                    x: merged.times, y: merged.values,
                    name: g.label + suffix,
                    mode: traceMode,
                    yaxis: yaxisName,
                    line: {color: color},
                    marker: {color: color}
                };
                if (axis === 'right') { trace.line.dash = 'dash'; }
                // When the band is on, surface its exact extremes in the
                // (x-unified) tooltip so the shaded area is readable as numbers.
                // Name goes in the template (matches the monitor charts) so it
                // stays visible alongside <extra></extra>.
                if (bandShown) {
                    trace.customdata = merged.times.map(function(_, i) {
                        return [merged.mins[i], merged.maxs[i]];
                    });
                    trace.hovertemplate = '<b>' + (g.label + suffix) + '</b><br>'
                        + cfg.aggregateFunc + ' %{y:.2f}'
                        + '  ·  range %{customdata[0]:.2f}–%{customdata[1]:.2f}'
                        + '<extra></extra>';
                }
                traces.push(trace);
                });
            }
        });

        if (traces.length > 0) Plotly.addTraces(chartDiv, traces);

        keys.forEach(function(k) {
            var axis = activeSeries[k].axis;
            var acfg = cfgFor(axis);
            // Box draws one trace per key (like the non-aggregated path), so it
            // keeps a real trace index even though aggregation may be enabled.
            if (acfg.chartType !== 'box' && acfg.aggregateEnabled) {
                activeSeries[k].traceIdx = -1;
            } else {
                activeSeries[k].traceIdx = traceIdxMap[k] != null ? traceIdxMap[k] : -1;
            }
        });
        // 'x unified' hover collects every trace at an x, which on grouped
        // boxplots pulls neighbouring boxes into one tooltip. Switch to
        // 'closest' so each box hovers alone; keep unified for line/scatter.
        var anyBox = ['left', 'right'].some(function(axis) {
            return keysByAxis[axis].length && cfgFor(axis).chartType === 'box';
        });
        Plotly.relayout(chartDiv, {hovermode: anyBox ? 'closest' : 'x unified'});
        updateIdealRange();
    }

    function fetchAndAdd(key, axis, cb) {
        var parts = key.split(':');
        var device = parts[0];
        var sensor = parts.slice(1).join(':');
        var url = '/api/series?device='
            + encodeURIComponent(device)
            + '&sensor=' + encodeURIComponent(sensor);
        if (startDate) url += '&start=' + startDate;
        if (endDate) url += '&end=' + endDate;
        var acfg = cfgFor(axis);
        // Boxplots build their distribution from raw points on the client, so
        // they always fetch raw (the agg func is ignored — the slider only
        // sets the client-side box-grouping width).
        if (acfg.chartType !== 'box'
            && acfg.aggregateEnabled && acfg.bucketMinutes > 0) {
            url += '&bkt=' + acfg.bucketMinutes
                 + '&agg=' + encodeURIComponent(acfg.aggregateFunc);
        }

        fetch(url)
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                var data = resp.data || [];
                if (data.length === 0) { if (cb) cb(); return; }

                var times = data.map(function(d) { return d.time; });
                var values = data.map(function(d) { return d.value; });
                var counts = data.map(function(d) {
                    return d.count != null ? d.count : 1; });
                // min/max ride along only on bucketed responses (range band).
                var mins = data.map(function(d) {
                    return d.min != null ? d.min : null; });
                var maxs = data.map(function(d) {
                    return d.max != null ? d.max : null; });

                seriesData[key] = {
                    times: times, values: values, counts: counts,
                    mins: mins, maxs: maxs
                };
                activeSeries[key] = {
                    axis: axis, traceIdx: -1, points: data.length,
                    truncated: !!resp.truncated,
                    limit: resp.limit || 0
                };
                totalPoints += data.length;
                showEmpty(false);
                if (cb) cb();
            });
    }

    // Re-fetch every active series with the current per-axis aggregation
    // config, then rebuild. Used whenever agg / bucket / split changes: the
    // client no longer caches raw rows to recompute from (server-side agg),
    // so a tiny refetch replaces the old free local recompute.
    function refetchAll() {
        var keys = Object.keys(activeSeries);
        if (keys.length === 0) { rebuildTraces(); syncUrl(); return; }
        var specs = keys.map(function(k) {
            return { key: k, axis: activeSeries[k].axis }; });
        totalPoints = 0;
        var done = 0;
        specs.forEach(function(s) {
            fetchAndAdd(s.key, s.axis, function() {
                done++;
                if (done === specs.length) {
                    rebuildTraces();
                    syncUrl();
                    updateStats();
                    updateY2();
                }
            });
        });
    }

    function addOrUpdateSeries(key, axis) {
        if (activeSeries[key]) {
            // Already loaded. The cached series was fetched for the old
            // axis; under split mode the new axis may have a different agg
            // config, so refetch this one key (tiny payload).
            totalPoints -= activeSeries[key].points || 0;
            activeSeries[key].axis = axis;
            fetchAndAdd(key, axis, function() {
                rebuildTraces();
                syncUrl();
                updateStats();
                updateY2();
            });
        } else {
            // Need to fetch — syncUrl after fetch completes
            showEmpty(false);
            fetchAndAdd(key, axis, function() {
                rebuildTraces();
                syncUrl();
                updateStats();
                updateY2();
            });
        }
    }

    function removeSeries(key) {
        if (!activeSeries[key]) return;
        totalPoints -= activeSeries[key].points || 0;
        delete activeSeries[key];
        delete seriesData[key];
        rebuildTraces();
        if (Object.keys(activeSeries).length === 0) {
            showEmpty(true);
        }
    }

    function updateY2() {
        var hasY2 = chartDiv.data.some(function(t) {
            return t.visible !== false && t.yaxis === 'y2';
        });
        var relayoutUpdate = {
            'yaxis2.visible': hasY2,
            'yaxis2.showticklabels': hasY2
        };
        // Update axis labels based on units
        var leftUnits = {};
        var rightUnits = {};
        Object.keys(activeSeries).forEach(function(k) {
            var s = allSensors.find(function(s) {
                return s.device + ':' + s.sensor === k;
            });
            var unit = (s && s.sensor_meta && s.sensor_meta.unit) || '';
            if (!unit) return;
            if (activeSeries[k].axis === 'right') rightUnits[unit] = true;
            else leftUnits[unit] = true;
        });
        var leftKeys = Object.keys(leftUnits);
        var rightKeys = Object.keys(rightUnits);
        applyIdealRangeAvailability();
        relayoutUpdate['yaxis.title.text'] = leftKeys.length === 1
            ? leftKeys[0] : '';
        relayoutUpdate['yaxis2.title.text'] = rightKeys.length === 1
            ? rightKeys[0] : '';
        Plotly.relayout(chartDiv, relayoutUpdate);
    }

    function updateIdealRange() {
        var shapes = [];
        // Ideal range is ambiguous with active dual Y axes; keep stored values but
        // suppress only ideal-range visuals, not other overlays.
        if (!hasDualAxesActive()) {
            var yref = idealRangeAxisRef();
            var lo = idealLo;
            var hi = idealHi;
            if (lo !== null && hi !== null && lo < hi) {
                shapes.push({
                    type: 'rect',
                    x0: 0, x1: 1, xref: 'paper',
                    yref: yref,
                    y0: lo, y1: hi,
                    fillcolor: 'rgba(34, 197, 94, 0.12)',
                    line: { width: 0 },
                    layer: 'below'
                });
            } else {
                var lineVal = lo !== null ? lo : hi;
                if (lineVal !== null) {
                    shapes.push({
                        type: 'line',
                        x0: 0, x1: 1, xref: 'paper',
                        yref: yref,
                        y0: lineVal, y1: lineVal,
                        line: { color: 'rgba(34, 197, 94, 0.85)', width: 1.5, dash: 'dash' }
                    });
                }
            }
        }

        Plotly.relayout(chartDiv, { shapes: shapes });
    }

    function updateStats() {
        if (statsDiv) {
            var t = 0;
            var truncatedKeys = [];
            Object.keys(activeSeries).forEach(function(k) {
                t += activeSeries[k].points || 0;
                if (activeSeries[k].truncated) {
                    truncatedKeys.push(k);
                }
            });
            var text = t > 0
                ? t.toLocaleString() + ' data points' : '';
            if (truncatedKeys.length > 0) {
                var limit = activeSeries[truncatedKeys[0]].limit;
                text += ' — ' + truncatedKeys.length
                    + (truncatedKeys.length === 1
                        ? ' series' : ' series')
                    + ' capped at '
                    + limit.toLocaleString()
                    + ' points (narrow the date range'
                    + ' to see all data)';
            }
            statsDiv.textContent = text;
            statsDiv.classList.toggle(
                'truncation-warning',
                truncatedKeys.length > 0);
        }
    }

    function showEmpty(show) {
        var el = document.getElementById('chart-empty');
        if (el) el.style.display = show ? 'flex' : 'none';
        chartDiv.style.display = show ? 'none' : 'block';
    }

    function syncUrl() {
        var left = [], right = [];
        Object.keys(activeSeries).sort().forEach(function(k) {
            if (activeSeries[k].axis === 'right') right.push(k);
            else left.push(k);
        });
        var p = new URLSearchParams(window.location.search);
        if (left.length) p.set('s', left.join(','));
        else p.delete('s');
        if (right.length) p.set('r', right.join(','));
        else p.delete('r');
        var L = axisCfg.left;
        if (L.labelFormat !== 'smart') p.set('lbl', L.labelFormat);
        else p.delete('lbl');
        if (L.chartType !== 'line') p.set('ct', L.chartType);
        else p.delete('ct');
        if (L.aggregateEnabled) p.set('agg', L.aggregateFunc);
        else p.delete('agg');
        if ((L.aggregateEnabled || L.chartType === 'box') && L.bucketMinutes !== 10) {
            p.set('bkt', L.bucketMinutes);
        } else p.delete('bkt');
        if (L.bandEnabled) p.set('band', '1');
        else p.delete('band');
        if (splitMode) {
            p.set('split', '1');
            var R = axisCfg.right;
            if (R.labelFormat !== L.labelFormat) p.set('lbl_r', R.labelFormat);
            else p.delete('lbl_r');
            if (R.chartType !== L.chartType) p.set('ct_r', R.chartType);
            else p.delete('ct_r');
            if (R.aggregateEnabled !== L.aggregateEnabled
                || (R.aggregateEnabled && R.aggregateFunc !== L.aggregateFunc)) {
                p.set('agg_r', R.aggregateEnabled ? R.aggregateFunc : 'off');
            } else {
                p.delete('agg_r');
            }
            if ((R.aggregateEnabled || R.chartType === 'box')
                && R.bucketMinutes !== L.bucketMinutes) {
                p.set('bkt_r', R.bucketMinutes);
            } else {
                p.delete('bkt_r');
            }
            // Right inherits left's band on load, so only emit band_r when it
            // differs (explicit '0' overrides an inherited-on state).
            if (R.bandEnabled !== L.bandEnabled) p.set('band_r', R.bandEnabled ? '1' : '0');
            else p.delete('band_r');
        } else {
            p.delete('split');
            p.delete('lbl_r');
            p.delete('ct_r');
            p.delete('agg_r');
            p.delete('bkt_r');
            p.delete('band_r');
        }
        if (idealLo !== null) p.set('ideal_lo', idealLo);
        else p.delete('ideal_lo');
        if (idealHi !== null) p.set('ideal_hi', idealHi);
        else p.delete('ideal_hi');
        var newUrl = window.location.pathname;
        var qs = p.toString();
        if (qs) newUrl += '?' + qs;
        history.replaceState(null, '', newUrl);
        syncDateFormParams();
    }

    // Preserve s/r params across date filter submissions by
    // injecting hidden fields into the form. This works for both
    // the Apply button and the preset buttons (which call
    // form.submit() directly, bypassing the submit event).
    var dateForm = document.getElementById('dateFilter');
    if (dateForm) {
        var params = new URLSearchParams(window.location.search);
        ['s', 'r', 'lbl', 'ct', 'agg', 'bkt', 'band',
         'split', 'lbl_r', 'ct_r', 'agg_r', 'bkt_r', 'band_r',
            'ideal_lo', 'ideal_hi'].forEach(function(name) {
            var val = params.get(name);
            if (val) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = name;
                input.value = val;
                dateForm.appendChild(input);
            }
        });
    }

    // Also keep hidden fields in sync when series change
    function syncDateFormParams() {
        if (!dateForm) return;
        ['s', 'r', 'lbl', 'ct', 'agg', 'bkt', 'band',
         'split', 'lbl_r', 'ct_r', 'agg_r', 'bkt_r', 'band_r',
         'ideal_lo', 'ideal_hi'].forEach(function(name) {
            var existing = dateForm.querySelector(
                'input[name="' + name + '"]');
            var p = new URLSearchParams(window.location.search);
            var val = p.get(name);
            if (val) {
                if (existing) {
                    existing.value = val;
                } else {
                    var input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = name;
                    input.value = val;
                    dateForm.appendChild(input);
                }
            } else if (existing) {
                existing.remove();
            }
        });
    }
})();
