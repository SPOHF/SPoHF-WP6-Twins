
    document.getElementById('theme-toggle').addEventListener('click', function() {
        var html = document.documentElement;
        var next = html.dataset.theme === 'dark' ? 'light' : 'dark';
        html.dataset.theme = next;
        localStorage.setItem('wp6-theme', next);
    });
