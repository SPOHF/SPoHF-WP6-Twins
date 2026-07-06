
(function() {
    var dashboardId = document.documentElement.dataset.dashboard;
    var STORAGE_KEY = 'wp6-dashboard-' + dashboardId;
    var saveBtn = document.getElementById('save-to-dashboard');
    var dialog = document.getElementById('save-dialog');
    if (!saveBtn || !dialog) return;

    saveBtn.addEventListener('click', function() {
        var params = new URLSearchParams(window.location.search);
        var s = params.get('s') || '';
        var r = params.get('r') || '';
        if (!s && !r) { alert('Select some sensors first.'); return; }

        var allKeys = (s + (r ? ',' + r : '')).split(',').filter(Boolean);
        var suggested = allKeys.slice(0, 3).join(', ') + (allKeys.length > 3 ? ' ...' : '');
        dialog.querySelector('#save-title').value = suggested;

        var start = params.get('start');
        var end = params.get('end');
        var days = 7;
        if (start && end) {
            days = Math.round((new Date(end) - new Date(start)) / 86400000);
        }
        dialog.querySelector('#save-relative-days').value = days;
        dialog.querySelector('#save-date-mode').checked = true;
        dialog.querySelector('#save-days-group').style.display = '';

        dialog.showModal();
    });

    dialog.querySelector('#save-date-mode').addEventListener('change', function() {
        dialog.querySelector('#save-days-group').style.display = this.checked ? '' : 'none';
    });

    dialog.querySelector('#save-confirm').addEventListener('click', function() {
        var params = new URLSearchParams(window.location.search);
        var title = dialog.querySelector('#save-title').value.trim();
        if (!title) { alert('Please enter a title.'); return; }

        var isRelative = dialog.querySelector('#save-date-mode').checked;
        var chart = {
            id: Math.random().toString(36).slice(2, 10),
            title: title,
            s: params.get('s') || '',
            r: params.get('r') || '',
            dateMode: isRelative ? 'relative' : 'absolute',
            relativeDays: parseInt(dialog.querySelector('#save-relative-days').value) || 7,
            start: params.get('start') || '',
            end: params.get('end') || '',
            lbl: params.get('lbl') || '',
            ct: params.get('ct') || '',
            agg: params.get('agg') || '',
            bkt: params.get('bkt') || '',
            band: params.get('band') || '',
            split: params.get('split') || '',
            lbl_r: params.get('lbl_r') || '',
            ct_r: params.get('ct_r') || '',
            agg_r: params.get('agg_r') || '',
            bkt_r: params.get('bkt_r') || '',
            band_r: params.get('band_r') || '',
            ideal_lo: params.get('ideal_lo') || '',
            ideal_hi: params.get('ideal_hi') || '',
            createdAt: new Date().toISOString()
        };

        var raw = localStorage.getItem(STORAGE_KEY);
        var data;
        try { data = raw ? JSON.parse(raw) : { version: 1, charts: [] }; }
        catch (e) { data = { version: 1, charts: [] }; }
        data.charts.push(chart);
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            alert('Could not save: storage may be full.');
            dialog.close();
            return;
        }

        dialog.close();
        var origText = saveBtn.textContent;
        saveBtn.textContent = 'Saved!';
        setTimeout(function() { saveBtn.textContent = origText; }, 2000);
    });

    dialog.querySelector('#save-cancel').addEventListener('click', function() {
        dialog.close();
    });
})();
