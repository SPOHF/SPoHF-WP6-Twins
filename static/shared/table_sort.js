
    function refreshGrouping(table) {
        var raw = table.dataset.groupCol;
        if (raw === undefined) return;
        var groupCol = parseInt(raw, 10);
        if (isNaN(groupCol)) return;
        // Find which header (if any) currently drives the sort.
        var ths = table.querySelectorAll('thead th');
        var sortedIdx = null;
        ths.forEach(function(th, i) {
            if (th.dataset.sortDir === 'asc' || th.dataset.sortDir === 'desc') {
                sortedIdx = i;
            }
        });
        // Merge only when no sort is active (initial render) or the active
        // sort matches the group column — otherwise rows aren't grouped.
        var shouldMerge = (sortedIdx === null || sortedIdx === groupCol);
        var rows = table.querySelectorAll('tbody tr');
        if (!shouldMerge) {
            rows.forEach(function(r) {
                var c = r.children[groupCol];
                if (c) c.classList.remove('cell-merged');
            });
            return;
        }
        var prev = null;
        rows.forEach(function(row) {
            var cell = row.children[groupCol];
            if (!cell) return;
            var key = cell.dataset.sort || cell.textContent.trim();
            if (key === prev) cell.classList.add('cell-merged');
            else { cell.classList.remove('cell-merged'); prev = key; }
        });
    }

    function sortTable(th) {
        var table = th.closest('table');
        var tbody = table.querySelector('tbody');
        var idx = Array.from(th.parentNode.children).indexOf(th);
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var asc = th.dataset.sortDir !== 'asc';
        // Reset all headers
        th.parentNode.querySelectorAll('th').forEach(function(h) {
            h.dataset.sortDir = '';
            h.textContent = h.textContent.replace(/ [\u25B2\u25BC]$/, '');
        });
        th.dataset.sortDir = asc ? 'asc' : 'desc';
        th.textContent += asc ? ' \u25B2' : ' \u25BC';
        rows.sort(function(a, b) {
            var ac = a.children[idx], bc = b.children[idx];
            var at = ac.dataset.sort || ac.textContent.trim();
            var bt = bc.dataset.sort || bc.textContent.trim();
            // Try numeric comparison (strip commas for formatted numbers)
            var an = parseFloat(at.replace(/,/g, ''));
            var bn = parseFloat(bt.replace(/,/g, ''));
            if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
            return asc ? at.localeCompare(bt) : bt.localeCompare(at);
        });
        rows.forEach(function(r) { tbody.appendChild(r); });
        refreshGrouping(table);
    }

    document.querySelectorAll('table[data-group-col]').forEach(refreshGrouping);
