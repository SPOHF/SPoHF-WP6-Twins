// Row-expansion for the crop-climate table: clicking a cell inserts a detail
// <tr> with an <iframe> chart (lazy-loaded from the chart endpoint). One detail
// row at a time; clicking the same cell again collapses it.
function ccChart(td){
  var table = td.closest('table'), tr = td.closest('tr');
  var key = tr.rowIndex + ':' + td.dataset.height + ':' + td.dataset.metric;
  var open = table.querySelector('tr.cc-detail');
  var same = open && open.dataset.key === key;
  if (open) open.remove();
  if (same) return;
  var dr = document.createElement('tr');
  dr.className = 'cc-detail'; dr.dataset.key = key;
  var cell = document.createElement('td');
  cell.colSpan = table.rows[0].cells.length; cell.style.padding = '0';
  var ifr = document.createElement('iframe');
  ifr.style.cssText = 'width:100%;height:400px;border:0;background:#fff;border-radius:8px;';
  ifr.srcdoc = '<p style="font:14px sans-serif;padding:1rem;color:#555;">Loading chart…</p>';
  cell.appendChild(ifr); dr.appendChild(cell);
  tr.parentNode.insertBefore(dr, tr.nextSibling);
  var q = new URLSearchParams({wire: table.dataset.wire, date: table.dataset.date,
                               height: td.dataset.height, metric: td.dataset.metric});
  fetch('/multi_height/crop-climate/chart?' + q.toString())
    .then(function(r){ return r.text(); })
    .then(function(h){ ifr.srcdoc = h; })
    .catch(function(){ ifr.srcdoc =
      '<p style="font:14px sans-serif;padding:1rem;color:#b91c1c;">Failed to load chart.</p>'; });
}
